"""Apex Gear + Time-Travel Mission Control. Run: python3 server.py  ->  http://localhost:8000"""
import json
import os
import select
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from timetravel import agent, appcode, db, seed, sse, tools

WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
WARM = {"ms": None, "at": None}
SHOW = ["APX-0007", "APX-0042", "APX-0100", "APX-0555", "APX-0777"]
JS_FILES = {"recovery_data.js", "recovery_view.js"}


def warm_loop():
    """Keeps the branch engine hot: proves a clone is cheap and reports how fast it is."""
    while True:
        try:
            with db.LOCK:
                c = db.connect()
                t = time.perf_counter()
                m = db.clone(c, ":memory:")
                WARM.update(ms=round((time.perf_counter() - t) * 1000, 1), at=time.time())
                m.close(); c.close()
        except Exception:
            pass
        time.sleep(4)


def api_state():
    with db.LOCK:
        c = db.connect()
        inv = c.execute("SELECT COUNT(*) n, SUM(stock) u, SUM(stock=0) z FROM inventory").fetchone()
        sample = [dict(r) for r in c.execute(
            f"SELECT sku,name,stock FROM inventory WHERE sku IN ({','.join('?' * len(SHOW))}) ORDER BY sku", SHOW)]
        orders = [dict(r) for r in c.execute(
            "SELECT id,customer_id,total_cents,status,created_at FROM orders ORDER BY id DESC LIMIT 6")]
        inc = tools.detect_incident(c)
        win = db.clock.now() - 600
        dots = [dict(r) for r in c.execute("SELECT id, created_at ts FROM orders WHERE created_at > ?", (win,))]
        evts = c.execute("SELECT COUNT(*) FROM changelog").fetchone()[0]
        c.close()
    src = appcode.read_source()
    return {"now": db.clock.now(), "inventory": {"skus": inv["n"], "units": inv["u"], "zero": inv["z"], "sample": sample},
            "orders": orders, "incident": inc, "order_dots": dots, "patched": "WHERE sku = ?" in src,
            "warm": {**WARM, "events": evts}}


def post(path, body):
    if path == "/api/orders":
        with db.LOCK:
            c = db.connect()
            try:
                return appcode.fn("place_order")(c, body)
            finally:
                c.close()
    if path == "/api/admin/sync-stock":
        with db.LOCK:
            c = db.connect()
            try:
                return appcode.fn("sync_stock")(c, body)
            finally:
                c.close()
    if path == "/api/demo/reset":
        agent.SESSIONS.clear(); seed.reset(); return {"ok": True}
    if path == "/api/demo/crash":     # the warehouse feed marks ONE sku sold out -> buggy handler wipes all
        return post("/api/admin/sync-stock", {"sku": "APX-0007", "stock": 0})
    if path == "/api/demo/orders":
        return {"orders": seed.demo_orders()}
    if path == "/api/rewind":
        return {"id": agent.start(body.get("prompt", "")).id}
    if path.startswith("/api/session/") and path.endswith("/approve"):
        return agent.approve(path.split("/")[3]).to_json()
    if path.startswith("/api/session/") and path.endswith("/undo"):
        return agent.undo(path.split("/")[3]).to_json()
    raise KeyError(path)


class H(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def log_message(self, *a):
        pass

    def _client_closed(self):
        try:
            readable, _, _ = select.select([self.connection], [], [], 0)
            if not readable:
                return False
            return self.connection.recv(1, socket.MSG_PEEK) == b""
        except (OSError, ValueError):
            return True

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            if self.path in ("/", "/index.html"):
                return self._send(200, open(os.path.join(WEB, "index.html"), "rb").read(), "text/html; charset=utf-8")
            if self.path == "/api/state":
                return self._send(200, api_state())

            parsed = urlsplit(self.path)
            if parsed.path.startswith("/js/"):
                name = parsed.path[4:]
                if name not in JS_FILES:
                    return self._send(404, {"error": "not found"})
                with open(os.path.join(WEB, "js", name), "rb") as handle:
                    return self._send(200, handle.read(), "application/javascript; charset=utf-8")

            if parsed.path.startswith("/api/session/") and parsed.path.endswith("/events"):
                parts = parsed.path.strip("/").split("/")
                sid = parts[2] if len(parts) > 2 else ""
                if not sse.validate_session_id(sid):
                    return self._send(400, {"error": "invalid session id"})
                try:
                    header_id = self.headers.get("Last-Event-ID")
                    query_id = parse_qs(parsed.query).get("last_event_id", [None])[0]
                    after_id = sse.parse_last_event_id(header_id if header_id is not None else query_id)
                except ValueError as error:
                    return self._send(400, {"error": str(error)})
                try:
                    historical = sse.read_events_after(sid, after_id)
                except Exception:
                    return self._send(500, {"error": "audit stream unavailable"})
                if not historical and sid not in agent.SESSIONS:
                    return self._send(404, {"error": "session or audit history not found"})

                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "keep-alive")
                self.send_header("X-Accel-Buffering", "no")
                self.end_headers()
                try:
                    self.wfile.write(b"retry: 3000\n\n")
                    self.wfile.flush()
                    for frame in sse.iter_sse_frames(sid, after_id, closed=self._client_closed):
                        self.wfile.write(frame.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass
                return

            if parsed.path.startswith("/api/session/") and parsed.path.endswith("/audit"):
                sid = parsed.path.split("/")[3]
                events = agent.audit_events(sid)
                if not events:
                    return self._send(404, {"error": "audit history not found"})
                return self._send(200, {"session_id": sid, "events": events})

            if parsed.path.startswith("/api/session/"):
                sid = parsed.path.split("/")[3]
                if sid not in agent.SESSIONS:
                    return self._send(404, {"error": "session not found"})
                return self._send(200, agent.SESSIONS[sid].to_json())

            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(500, {"error": str(e)})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._send(200, post(self.path, body))
        except KeyError as e:
            self._send(404, {"error": f"unknown route {e}"})
        except Exception as e:
            self._send(400, {"error": str(e)})


if __name__ == "__main__":
    if not os.path.exists(db.LIVE):
        seed.reset()
    appcode.reload()
    threading.Thread(target=warm_loop, daemon=True).start()
    port = int(os.getenv("PORT", "8000"))
    print(f"Mission Control on http://localhost:{port}")
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()
