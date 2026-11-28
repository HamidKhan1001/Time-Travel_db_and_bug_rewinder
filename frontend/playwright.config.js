import os from 'node:os'
import path from 'node:path'
import { defineConfig } from '@playwright/test'

// Runs the real Python server (fresh seed) on its own port and drives the built React app at /app/.
//   npm run test:e2e                    builds the live bundle, then runs (uses Playwright's Chromium)
//   PW_CHANNEL=chrome npm run test:e2e  use an installed Google Chrome instead of downloading Chromium
const PORT = 8123
// A second server with deliberately tight rate limits and its own data directory (TT_DATA_DIR), used only by
// ratelimit.spec.js, so limit tests can never starve the other specs.
const LIMITED_PORT = 8124
const LIMITED_DATA_DIR = path.join(os.tmpdir(), 'tt-e2e-ratelimited')

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
  webServer: [
    {
      command: 'python3 reset.py && python3 server.py',
      cwd: '..',
      // Roomy limits: every spec resets the demo and polls, which is normal for tests but not for real clients.
      env: { PORT: String(PORT), TT_PACE: '0', TT_RATE_WRITE_PER_MIN: '6000', TT_RATE_WRITE_BURST: '1000', TT_RATE_READ_PER_MIN: '60000', TT_RATE_READ_BURST: '10000' },
      url: `http://127.0.0.1:${PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: 'python3 server.py',
      cwd: '..',
      env: {
        PORT: String(LIMITED_PORT),
        TT_PACE: '0',
        TT_DATA_DIR: LIMITED_DATA_DIR,
        TT_RATE_READ_PER_MIN: '60', // 1 token per second
        TT_RATE_READ_BURST: '5',
        TT_RATE_WRITE_PER_MIN: '60',
        TT_RATE_WRITE_BURST: '2',
      },
      url: `http://127.0.0.1:${LIMITED_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
