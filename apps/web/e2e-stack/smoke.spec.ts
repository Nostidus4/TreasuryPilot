import { expect, test } from '@playwright/test';

import { installWallet, ownerSession, stack } from './support';

test('smoke: owner session on the real API', async ({ page, context }) => {
  await installWallet(context);
  await ownerSession(page);
  const { orgId, treasuryId } = stack();
  await page.goto(`/o/${orgId}/t/${treasuryId}/payees`);
  await page.screenshot({ path: 'test-results/smoke.png' });
  await expect(page.getByRole('heading', { name: 'Payees' }).first()).toBeVisible();
});
