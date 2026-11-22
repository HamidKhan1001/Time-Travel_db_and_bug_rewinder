import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf8'))

// The team's Python server (server.py at the repository root) listens on 127.0.0.1:8000
// and sends no CORS headers. In development, Vite forwards /api requests to it so the
// React app can call the real backend from http://localhost:5173 without changing server.py.
// Override with API_PROXY_TARGET, e.g. API_PROXY_TARGET=http://127.0.0.1:8001 npm run dev
const apiProxyTarget = process.env.API_PROXY_TARGET || 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig(({ command }) => ({
  // The Python server serves the production build under /app/ (see server.py).
  base: command === 'build' ? '/app/' : '/',
  plugins: [react()],
  define: {
    __APP_VERSION__: JSON.stringify(pkg.version),
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiProxyTarget,
        changeOrigin: true,
      },
    },
  },
}))
