import { expect, test, type Page } from '@playwright/test';

const anvilRpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://127.0.0.1:8545';

async function signIn(page: Page, email: string) {
  // Keep the in-browser mock database alive when signing in again after a
  // sign-out. The sign-out flow already returns to /login in the SPA.
  if (!new URL(page.url()).pathname.endsWith('/login')) {
    await page.goto('/login');
  }
  await page.getByLabel('Work email').fill(email);
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  await expect(page).toHaveURL(/\/o\/org_northwind/);
}

test.beforeEach(async ({ request }) => {
  if (!process.env.E2E_ANVIL_RPC_URL) return;
  const response = await request.post(anvilRpcUrl, {
    data: { jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] },
  });
  expect(response.ok()).toBeTruthy();
  const payload: unknown = await response.json();
  expect(payload).toMatchObject({ result: '0x7a69' });
});

test('create and submit a request, then approve it with the demo signer', async ({
  page,
}) => {
  await signIn(page, 'linh@northwind.test');
  await page.getByRole('link', { name: 'Requests' }).click();
  await page.getByRole('link', { name: 'New request' }).click();

  await page.getByLabel('Vendor').click();
  await page.getByRole('option', { name: 'Acurast Cloud' }).click();
  await page.getByLabel('Invoice number').fill('E2E-WEB-023-001');
  await page.getByLabel('Amount').fill('145.25');
  await page.getByLabel('Due date').fill('2099-01-15');
  await page.getByLabel('Description').fill('Playwright browser flow');
  await page.getByRole('button', { name: 'Save draft' }).click();

  await expect(page).toHaveURL(/\/o\/org_northwind\/requests\/req_/);
  const requestId = new URL(page.url()).pathname.match(
    /\/requests\/(req_[^/]+)/,
  )?.[1];
  expect(requestId).toBeTruthy();
  await page
    .getByRole('button', { name: 'Confirm and submit for approval' })
    .click();
  await expect(page.getByText('Waiting for an approver')).toBeVisible();

  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, 'an@northwind.test');

  await page.getByRole('link', { name: 'Requests' }).click();
  await page
    .getByRole('row', { name: 'Open request E2E-WEB-023-001' })
    .click();
  await page.getByRole('link', { name: 'Open in approvals' }).click();
  await page
    .getByRole('button', { name: 'Connect wallet to continue' })
    .click();
  await page.getByRole('button', { name: /Demo signer/ }).click();
  await page.getByRole('button', { name: 'Sign approval' }).click();
  await expect(page.getByText('Approved', { exact: true })).toBeVisible();
});

test('execute a seeded plan, verify payment, and reconcile its receipt', async ({
  page,
}) => {
  await signIn(page, 'linh@northwind.test');
  await page.getByRole('link', { name: 'Plans' }).click();
  await page.getByRole('row', { name: 'Open plan pln_0421' }).click();
  await page.getByRole('button', { name: 'Run now' }).click();
  await expect(page.getByText('All steps verified')).toBeVisible({
    timeout: 35_000,
  });

  await page.getByRole('link', { name: 'Reconciliation' }).click();
  await page.getByRole('row', { name: 'Open payment BP-2026-219' }).click();
  await expect(page.getByText('Evidence is incomplete')).toHaveCount(0);
  await page.getByRole('button', { name: 'Mark as matched' }).click();
  await expect(page.getByText('Marked as matched')).toBeVisible();
});
