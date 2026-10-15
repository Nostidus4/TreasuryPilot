import { expect, test, type Page } from '@playwright/test';

import { APPROVER } from '../src/mocks/seeded';

const requesterEmail = 'linh@northwind.test';

const anvilRpcUrl = process.env.E2E_ANVIL_RPC_URL ?? 'http://127.0.0.1:8545';

async function signIn(page: Page, email: string) {
  // Keep the in-browser mock database alive when signing in again after a
  // sign-out. The sign-out flow already returns to /login in the SPA.
  if (!new URL(page.url()).pathname.endsWith('/login')) {
    await page.goto('/login');
  }
  const emailField = page.getByLabel('Work email');
  await expect(emailField).toBeVisible();
  await emailField.fill(email);
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  await expect(page).toHaveURL(/\/o\/org_northwind/);
}

test('Anvil RPC is reachable', async ({ request }) => {
  if (!process.env.E2E_ANVIL_RPC_URL) {
    // CI must prove Anvil is up; locally the check is opt-in.
    expect(process.env.CI, 'E2E_ANVIL_RPC_URL must be set in CI').toBeFalsy();
    test.skip(true, 'E2E_ANVIL_RPC_URL is not set');
  }
  const response = await request.post(anvilRpcUrl, {
    data: { jsonrpc: '2.0', id: 1, method: 'eth_chainId', params: [] },
  });
  expect(response.ok()).toBeTruthy();
  const payload: unknown = await response.json();
  expect(payload).toMatchObject({ result: '0x7a69' });
});

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`WEB-010 links to the API position card without horizontal overflow at ${viewport.width}px`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await signIn(page, requesterEmail);

    if (viewport.width === 1280) {
      await page.getByRole('link', { name: 'Requests' }).click();
      await page.getByRole('link', { name: 'Overview' }).click();
    } else {
      await page.goto('/o/org_northwind/t/trs_main');
    }
    await expect(page).toHaveURL(/\/o\/org_northwind\/t\/trs_main$/);

    const position = page.getByRole('group', { name: 'Position breakdown' });
    await expect(position).toBeVisible();
    await expect(position).toContainText('61,440.00');
    await expect(position).toContainText('101,560.00');
    await expect(position).toContainText('23,440.00');
    await expect(position).toContainText('38,000.00');

    const columns = await position.evaluate(
      (element) =>
        getComputedStyle(element).gridTemplateColumns.trim().split(/\s+/)
          .length,
    );
    expect(columns).toBe(viewport.width >= 768 ? 2 : 1);
    const horizontalOverflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(horizontalOverflow).toBeLessThanOrEqual(0);
  });
}

test('create a request, approve it, run its automatic plan, and match that payment', async ({
  page,
}) => {
  await signIn(page, requesterEmail);
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
  await signIn(page, APPROVER.email);

  await page.getByRole('link', { name: 'Requests' }).click();
  await page.getByRole('row', { name: 'Open request E2E-WEB-023-001' }).click();
  await page.getByRole('link', { name: 'Open in approvals' }).click();
  await page
    .getByRole('button', { name: 'Connect wallet to continue' })
    .click();
  await page.getByRole('button', { name: /Demo signer/ }).click();
  await page.getByRole('button', { name: 'Sign approval' }).click();
  await expect(
    page
      .getByRole('status')
      .filter({ hasText: 'This request is no longer waiting for approval.' })
      .getByText('Scheduled', { exact: true }),
  ).toBeVisible();

  await page.getByRole('button', { name: 'Account menu' }).click();
  await page.getByRole('menuitem', { name: 'Sign out' }).click();
  await expect(page).toHaveURL(/\/login$/);
  await signIn(page, requesterEmail);

  await page.getByRole('link', { name: 'Plans' }).click();
  const requestPlan = page.getByRole('row').filter({ hasText: '145.25' });
  await expect(requestPlan).toHaveCount(1);
  await requestPlan.click();
  await expect(page.getByText('Pay Acurast Cloud')).toBeVisible();
  const planId = new URL(page.url()).pathname.match(/\/plans\/([^/]+)$/)?.[1];
  expect(planId).toBeTruthy();
  const timeline = page.getByRole('list', { name: 'Execution steps' });
  let submittedHash: string | undefined;
  const submittedPlanResponse = page.waitForResponse(async (response) => {
    if (
      response.request().method() !== 'GET' ||
      !response.url().endsWith(`/v1/orgs/org_northwind/plans/${planId}`)
    ) {
      return false;
    }
    const plan = (await response.json()) as {
      steps: Array<{ status: string; txHash?: string }>;
    };
    submittedHash = plan.steps.find(
      (step) => step.status === 'Submitted' && step.txHash,
    )?.txHash;
    return Boolean(submittedHash);
  });
  const submittedAt = Date.now();
  await page.getByRole('button', { name: 'Run now' }).click();
  await expect(
    timeline
      .getByText('Sent — waiting for the network', { exact: true })
      .first(),
  ).toBeVisible({ timeout: 2_000 });
  expect(Date.now() - submittedAt).toBeLessThan(2_000);
  await submittedPlanResponse;
  expect(submittedHash).toMatch(/^0x[\da-f]{64}$/i);
  await expect
    .poll(async () =>
      timeline
        .getByRole('link', { name: 'Open transaction in the block explorer' })
        .evaluateAll((links) =>
          links.map((link) => (link as HTMLAnchorElement).href),
        ),
    )
    .toContain(`https://sepolia.etherscan.io/tx/${submittedHash}`);

  await expect(
    page.getByText('All checked module event fields match'),
  ).toBeVisible({ timeout: 35_000 });
  await expect(
    page.getByText('Event matched checked fields · 3 confirmations'),
  ).toBeVisible();

  await page.getByRole('link', { name: 'Reconciliation' }).click();
  await page.getByRole('row', { name: 'Open payment E2E-WEB-023-001' }).click();
  await expect(page.getByText('Evidence is incomplete')).toHaveCount(0);
  await page.getByRole('button', { name: 'Mark as matched' }).click();
  await expect(page.getByText('Marked as matched')).toBeVisible();
});

test('an unknown execution outcome stays in chain-checking state', async ({
  page,
}) => {
  await signIn(page, requesterEmail);
  await page.goto('/o/org_northwind/t/trs_main/plans/pln_0419');

  const timeline = page.getByRole('list', { name: 'Execution steps' });
  const checking = timeline.getByText(
    'Checking the chain — no new payment will be sent',
  );
  await expect(checking).toBeVisible();
  await expect(timeline.getByText('Failed', { exact: true })).toHaveCount(0);
  await expect(checking.locator('xpath=ancestor::li')).not.toContainText(
    /failed|error|revert/i,
  );
});

test('WEB-024 owner accepts the fee proposal and Finance pays a held plan', async ({
  page,
}) => {
  await signIn(page, requesterEmail);
  await page.goto('/o/org_northwind/t/trs_main/settings/fees');

  await expect(page.getByText('is waiting on a network fee')).toBeVisible();
  await page.getByRole('button', { name: /Pay now at/ }).click();
  await expect(page.getByText('is waiting on a network fee')).toBeHidden();

  await page.getByRole('button', { name: 'Accept', exact: true }).click();
  await expect(page.getByText('Preset Normal').first()).toBeVisible();
});
