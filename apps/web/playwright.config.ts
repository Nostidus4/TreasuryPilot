import { defineConfig, devices } from '@playwright/test';

// Dedicated port so a stray dev/preview server on 4173/5173 is never reused.
const port = 4179;
const rpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://127.0.0.1:8545';

export default defineConfig({
  testDir: './e2e',
  testIgnore: 'demo-*.spec.ts',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 45_000,
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: {
    command: `pnpm dev --host 127.0.0.1 --port ${port} --strictPort`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      VITE_API_MOCK: 'true',
      VITE_API_URL: '',
      VITE_RPC_URL: rpcUrl,
    },
  },
});
