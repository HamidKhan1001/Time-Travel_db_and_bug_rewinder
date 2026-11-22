import { defineConfig } from '@playwright/test'

// Runs the real Python server (fresh seed) on its own port and drives the built React app at /app/.
//   npm run test:e2e                    builds the live bundle, then runs (uses Playwright's Chromium)
//   PW_CHANNEL=chrome npm run test:e2e  use an installed Google Chrome instead of downloading Chromium
const PORT = 8123

export default defineConfig({
  testDir: './e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  workers: 1, // the demo database is shared state
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel: process.env.PW_CHANNEL || undefined,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'python3 reset.py && python3 server.py',
    cwd: '..',
    env: { PORT: String(PORT), TT_PACE: '0' },
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
})
