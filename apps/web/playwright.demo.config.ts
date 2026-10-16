import { defineConfig, devices } from '@playwright/test';

// The recordable demo scenario (docs/demo): the dev server runs with the demo profile on.
const port = 4180;
// Set DEMO_BASE_URL (with a trailing slash) to run against an already running preview build.
const external = process.env.DEMO_BASE_URL;

export default defineConfig({
  testDir: './e2e',
  testMatch: 'demo-*.spec.ts',
  fullyParallel: false,
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 150_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: external ?? `http://127.0.0.1:${port}/`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: external
    ? undefined
    : {
        command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
        url: `http://127.0.0.1:${port}`,
        reuseExistingServer: !process.env.CI,
        timeout: 120_000,
        env: {
          VITE_API_MOCK: 'true',
          VITE_API_URL: '',
          VITE_DEMO_SCENARIO: 'TP-DEMO-7M30-01',
        },
      },
});
