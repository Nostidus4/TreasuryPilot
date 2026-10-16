import { defineConfig, devices } from '@playwright/test';

// Runs against the real local stack (`make dev && make seed`): web, API, worker, signer, Anvil.
export default defineConfig({
  testDir: './e2e-stack',
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? 'github' : 'list',
  timeout: 240_000,
  expect: { timeout: 15_000 },
  use: {
    baseURL: process.env.E2E_STACK_URL ?? 'http://localhost:5173',
    trace: 'retain-on-failure',
    ...devices['Desktop Chrome'],
  },
});
