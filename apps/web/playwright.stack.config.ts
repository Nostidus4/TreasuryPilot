import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { defineConfig, devices } from '@playwright/test';

// Full-stack E2E: the real API, Postgres and Anvil with the mock API off.
// Prerequisites (CI starts them; locally `make e2e-stack` does): Postgres, Anvil on :8545, and
// `pnpm e2e:stack:setup` (migrate, deploy-local, seed) before this config runs.
const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const webPort = 4179;
const apiPort = 8000;
const ctlPort = 8790;
const rpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://127.0.0.1:8545';
// The API sets Secure cookies; Chromium accepts those over plain http only for localhost.
const webOrigin = `http://localhost:${webPort}`;

export default defineConfig({
  testDir: './e2e-stack',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  use: {
    baseURL: webOrigin,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    ...devices['Desktop Chrome'],
  },
  webServer: [
    {
      command: `uv run --frozen uvicorn treasurypilot_api.main:app --host 127.0.0.1 --port ${apiPort}`,
      cwd: repoRoot,
      url: `http://127.0.0.1:${apiPort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      env: {
        TP_ENVIRONMENT: 'local',
        // Public test-only AES key so TOTP enrolment (step-up) works; never a real secret.
        TP_FIELD_ENCRYPTION_KEY: 'dHJlYXN1cnlwaWxvdC1lMmUtZmllbGQta2V5LTAwMDA=',
        TP_CORS_ORIGINS: webOrigin,
        TP_MAGIC_LINK_BASE_URL: `${webOrigin}/auth/verify`,
        TP_PLATFORM_CHAIN_CONFIG_PATH: path.join(repoRoot, 'deployments/local/chains.json'),
        TP_DEPLOYMENTS_DIR: path.join(repoRoot, 'deployments/local'),
      },
    },
    {
      command: 'uv run --frozen python infra/scripts/e2e_stack.py ctl',
      cwd: repoRoot,
      url: `http://127.0.0.1:${ctlPort}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: { E2E_CTL_PORT: String(ctlPort), E2E_ANVIL_RPC_URL: rpcUrl },
    },
    {
      command: `pnpm dev --host localhost --port ${webPort} --strictPort`,
      url: webOrigin,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        VITE_API_MOCK: 'false',
        VITE_API_URL: '/api',
        VITE_CHAIN_ID: '31337',
        VITE_RPC_URL: rpcUrl,
        E2E_API_PROXY_TARGET: `http://127.0.0.1:${apiPort}`,
      },
    },
  ],
});
