import { readFileSync } from 'node:fs';

import { expect, test, type Page } from '@playwright/test';

// Anvil account 2 (public dev key, never holds real funds): the seeded approver's wallet.
const APPROVER_WALLET = '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC';
// localhost, not 127.0.0.1: the web CSP only allows http://localhost:* for connect-src.
const anvilRpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://localhost:8545';

const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * The one-time sign-in link `make seed` printed for a seeded user. Links are
 * single-use: run `make seed | tee <log>` (E2E_SEED_LOG) before every run.
 */
function seedLoginLink(name: string): string {
  const log = process.env.E2E_SEED_LOG;
  if (!log)
    throw new Error('E2E_SEED_LOG must point at the `make seed` output');
  const match = new RegExp(
    `^\\s*${escapeRegExp(name)}@seed\\.treasurypilot\\.test: (\\S+)$`,
    'm',
  ).exec(readFileSync(log, 'utf8'));
  if (!match)
    throw new Error(
      `no seeded login link for ${name} in ${log}; run \`make seed\` (piped to the log) before each run`,
    );
  return match[1];
}

/**
 * Mock wallet: an EIP-1193 provider whose methods are answered by Anvil, which
 * holds the dev account unlocked. The signatures are real ECDSA/EIP-712 ones.
 */
async function installMockWallet(page: Page, account: string) {
  await page.addInitScript(
    ({ account, rpcUrl }) => {
      const send = async (method: string, params: unknown[] = []) => {
        const response = await fetch(rpcUrl, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }),
        });
        const payload = (await response.json()) as {
          result?: unknown;
          error?: { message: string };
        };
        if (payload.error) throw new Error(payload.error.message);
        return payload.result;
      };
      (window as unknown as { ethereum: unknown }).ethereum = {
        isMockWallet: true,
        request: ({
          method,
          params,
        }: {
          method: string;
          params?: unknown[];
        }) =>
          method === 'eth_requestAccounts' || method === 'eth_accounts'
            ? Promise.resolve([account])
            : send(method, params),
        on: () => undefined,
        removeListener: () => undefined,
      };
    },
    { account, rpcUrl: anvilRpcUrl },
  );
}

test('the approver signs in and links the mock wallet on the real API', async ({
  page,
}) => {
  await installMockWallet(page, APPROVER_WALLET);
  await page.goto(seedLoginLink('approver'));
  await expect(page).toHaveURL(/\/o\/[^/]+\/t\/[^/]+$/);
  // The seeded AwaitingApproval request shows up in the real approval queue.
  await expect(page.getByRole('link', { name: /Approvals\s*1/ })).toBeVisible();

  await page.goto('/me/wallets');
  await page.getByRole('button', { name: 'Connect wallet' }).click();
  await page.getByRole('button', { name: 'Browser wallet' }).click();
  const sign = page.getByRole('button', { name: 'Sign to link this wallet' });
  const linked = page.getByText('Linked to your account', { exact: true });
  // A rerun against the same database finds the wallet already linked.
  await expect(sign.or(linked)).toBeVisible();
  if (await sign.isVisible()) await sign.click();
  await expect(
    page.getByText('Linked to your account', { exact: true }),
  ).toBeVisible();
});

// WEB-023's full flow. It cannot run on the local stack yet; each blocker was
// found by driving the API by hand. Remove `fixme` as they are closed.
//  - API: no GET /requests list or detail, so the request, approvals, plans
//    and reconciliation pages cannot load real data; the new-request form
//    needs vendors to carry payeeAddress (GET /vendors does not).
//  - API: POST /requests/{id}/approve answers 503 RPC_UNAVAILABLE because
//    nothing sets app.state.approval_chain_reader outside tests.
//  - Stack: approval needs MFA step-up, which needs TP_FIELD_ENCRYPTION_KEY
//    (unset in infra/env/.env.example), and the web has no MFA enrolment UI.
//  - Unverified: the worker's auto plan, execution to Paid, and the Matched
//    reconciliation, because they sit behind approval.
test.fixme('create a request, approve it, auto plan, paid, matched', () => {});
