import { createHmac } from 'node:crypto';
import { readFileSync } from 'node:fs';

import { expect, test, type BrowserContext, type Page } from '@playwright/test';

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

/** RFC 6238 (SHA-1, 6 digits, 30 s) for an unpadded base32 secret, at `offset` steps from now. */
function totp(secret: string, offset = 0): string {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  let bits = '';
  for (const char of secret.toUpperCase())
    bits += alphabet.indexOf(char).toString(2).padStart(5, '0');
  const key = Buffer.from(
    (bits.match(/.{8}/g) ?? []).map((byte) => parseInt(byte, 2)),
  );
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + offset));
  const mac = createHmac('sha1', key).update(counter).digest();
  const at = mac[mac.length - 1] & 0xf;
  const value = mac.readUInt32BE(at) & 0x7fffffff;
  return String(value % 1_000_000).padStart(6, '0');
}

// One serial story across two signed-in people (a seeded magic link works once).
test.describe
  .serial('create, approve, plan, pay, match on the real stack', () => {
  let approverContext: BrowserContext;
  let financeContext: BrowserContext;
  let approver: Page;
  let finance: Page;
  let invoice: string;
  let requestPath: string;
  let totpSecret: string;

  test.beforeAll(async ({ browser, baseURL }) => {
    approverContext = await browser.newContext({ baseURL });
    financeContext = await browser.newContext({ baseURL });
    approver = await approverContext.newPage();
    finance = await financeContext.newPage();
    await installMockWallet(approver, APPROVER_WALLET);
  });

  test.afterAll(async () => {
    await approverContext.close();
    await financeContext.close();
  });

  test('the approver signs in and links the mock wallet on the real API', async () => {
    const page = approver;
    await page.goto(seedLoginLink('approver'));
    await expect(page).toHaveURL(/\/o\/[^/]+\/t\/[^/]+$/);
    // Seeded (and earlier runs') AwaitingApproval requests show up in the real approval queue.
    await expect(
      page.getByRole('link', { name: /Approvals\s*\d+/ }),
    ).toBeVisible();

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

  test('finance creates a draft request and submits it for approval on the real API', async () => {
    const page = finance;
    await page.goto(seedLoginLink('finance'));
    await expect(page).toHaveURL(/\/o\/[^/]+\/t\/[^/]+$/);
    await page.getByRole('link', { name: 'Requests' }).click();
    await page.getByRole('link', { name: 'New request' }).click();
    await page.getByLabel('Vendor').click();
    // Seeded vendor with an Active payee (the others are still Cooling).
    await page.getByRole('option', { name: 'Acme Supplies (TEST)' }).click();
    invoice = `E2E-STACK-${Date.now()}`;
    await page.getByLabel('Invoice number').fill(invoice);
    await page.getByLabel('Amount').fill('145.25');
    // The planner opens a request's window 24 h before its due date at 00:00 UTC, so tomorrow's UTC
    // date is always inside it, and never before the (browser-local) issue date, in any timezone.
    await page
      .getByLabel('Due date')
      .fill(new Date(Date.now() + 24 * 3_600_000).toISOString().slice(0, 10));
    await page.getByLabel('Description').fill('Stack create flow');
    await page.getByRole('button', { name: 'Save draft' }).click();
    // The detail page reads GET /requests/{id}.
    await expect(page).toHaveURL(/\/requests\/[0-9a-f-]{36}$/);
    await expect(page.getByText(invoice).first()).toBeVisible();
    // The form has no fiat valuation field yet and the Travel Rule gate at approval needs one:
    // set it through the API the web calls (the stack's TEST static FX provider quotes USD 1:1).
    const [, orgId, requestId] =
      /\/o\/([^/]+)\/.*requests\/([0-9a-f-]{36})$/.exec(
        new URL(page.url()).pathname,
      ) ?? [];
    const patched = await page.evaluate(
      async ({ orgId, requestId }) => {
        const url = `http://localhost:8000/v1/orgs/${orgId}/requests/${requestId}`;
        // Cross-origin, so the cookie is unreadable: the web keeps the CSRF token in sessionStorage.
        const csrf = window.sessionStorage.getItem('treasurypilot.csrf') ?? '';
        const current = (await (
          await fetch(url, { credentials: 'include' })
        ).json()) as { version?: string };
        if (current.version === undefined)
          return { status: 0, body: JSON.stringify(current) };
        const response = await fetch(url, {
          method: 'PATCH',
          credentials: 'include',
          headers: {
            'content-type': 'application/json',
            'if-match': current.version,
            'x-csrf-token': csrf,
          },
          body: JSON.stringify({
            fiatAmountMinorUnits: '14525',
            fiatCurrency: 'USD',
          }),
        });
        return { status: response.status, body: await response.text() };
      },
      { orgId, requestId },
    );
    expect(patched.status, patched.body).toBe(200);
    await page.reload();
    await page
      .getByRole('button', { name: 'Confirm and submit for approval' })
      .click();
    await expect(page.getByText('Waiting for an approver')).toBeVisible();
    requestPath = new URL(page.url()).pathname;
  });

  test('the approver enrols an authenticator app', async () => {
    const page = approver;
    await page.goto('/me/security');
    await page
      .getByRole('button', { name: 'Set up authenticator app' })
      .click();
    totpSecret = (await page.getByTestId('totp-secret').textContent()) ?? '';
    expect(totpSecret).toMatch(/^[A-Z2-7]+$/);
    // The code for the previous 30 s step: step-up below uses a later step, because the
    // API accepts each time step once.
    await page.getByLabel('Authenticator code').fill(totp(totpSecret, -1));
    await page.getByRole('button', { name: 'Enable authenticator' }).click();
    await expect(page.getByText('Authenticator enabled').first()).toBeVisible();
  });

  // Reruns need `make seed` first: it resets the approver's MFA, which this file enrols.
  test('the approver signs the typed data and the API records the approval', async () => {
    const page = approver;
    await page.goto(requestPath.replace('/requests/', '/approvals/'));
    await expect(page.getByText(invoice).first()).toBeVisible();
    const approve = page.waitForResponse(
      (response) =>
        response.url().endsWith('/approve') &&
        response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: 'Sign approval' }).click();
    // Enrolment just stepped this session up, so no code is asked for here (the dialog is
    // covered by a unit test).
    const response = await approve;
    expect(response.status(), await response.text()).toBe(200);
  });

  // After the approval the worker plans (rule-based fallback, no AI key), the signer attests the
  // plan, the worker executes it on Anvil (PlanAttestedExecutor -> module) and the reconciliation
  // is matched automatically; each step is picked up by a beat task, so poll generously.
  test('approval is recorded, then auto plan, paid, matched', async () => {
    test.setTimeout(360_000);
    const page = approver;
    await page.goto(requestPath);
    await expect(async () => {
      await page.reload();
      await expect(page.getByTestId('request-status').getByText('Paid', { exact: true })).toBeVisible(
        {
          timeout: 2_000,
        },
      );
    }).toPass({ timeout: 150_000, intervals: [3_000] });
    await expect(page.getByText(invoice).first()).toBeVisible();

    const [, orgId, requestId] =
      /\/o\/([^/]+)\/.*requests\/([0-9a-f-]{36})$/.exec(requestPath) ?? [];
    await expect(async () => {
      const matched = await finance.evaluate(
        async ({ orgId, requestId }) => {
          const response = await fetch(
            `http://localhost:8000/v1/orgs/${orgId}/reconciliations?status=Matched`,
            { credentials: 'include' },
          );
          const body = (await response.json()) as {
            items?: Array<{ requestId: string }>;
          };
          return (body.items ?? []).some(
            (item) => item.requestId === requestId,
          );
        },
        { orgId, requestId },
      );
      expect(matched).toBe(true);
    }).toPass({ timeout: 120_000, intervals: [3_000] });
  });
});
