# syntax=docker/dockerfile:1

# ---- 1. build the React UI (live mode: talks to the API on the same origin) ----
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build:live

# ---- 2. runtime: Python standard library + SQLite, no third-party packages ----
FROM python:3.15-slim
ENV PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000
WORKDIR /srv/app

RUN useradd --system --uid 10001 --home-dir /srv/app timetravel
COPY --chown=timetravel timetravel/ timetravel/
# app/ is rewritten by the agent when it patches the buggy handler, so it must be writable.
COPY --chown=timetravel app/ app/
COPY --chown=timetravel seed/ seed/
COPY --chown=timetravel server.py reset.py ./
COPY --from=ui --chown=timetravel /ui/dist frontend/dist
RUN mkdir -p data && chown timetravel data

# Optional AI providers: docker build --build-arg EXTRAS=gemini|bedrock|ai .
ARG EXTRAS=""
COPY pyproject.toml README.md LICENSE ./
RUN if [ -n "$EXTRAS" ]; then pip install --no-cache-dir ".[${EXTRAS}]"; fi

USER timetravel
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status == 200 else 1)"
CMD ["python", "server.py"]
