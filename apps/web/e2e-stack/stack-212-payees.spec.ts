import { randomBytes } from 'node:crypto';

import { expect, test } from '@playwright/test';

import {
  advanceTime,
  connectWallet,
  installWallet,
  loginAs,
  ownerSession,
  stack,
  tick,
  users,
} from './support';

test('#212 payee: propose, out-of-band check, Owner registers it, Screening to Cooling to Active', async ({
  page,
  context,
}) => {
  const { orgId, treasuryId } = stack();
  const payeesUrl = `/o/${orgId}/t/${treasuryId}/payees`;
  const address = `0x${randomBytes(20).toString('hex')}`;
  const label = `E2E payee ${address.slice(2, 8)}`;

  await installWallet(context);
  await ownerSession(page);
  await page.goto(payeesUrl);

  await page.getByRole('button', { name: 'Propose payee' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Vendor').click();
  await page.getByRole('option', { name: /Globex/ }).click();
  await dialog.getByLabel('Label').fill(label);
  await dialog.getByLabel('Wallet address').fill(address);
  await dialog.getByRole('button', { name: 'Propose payee' }).click();

  // The local screening provider answers at once, so the row lands at the owner check with a
  // recorded CLEAR result.
  const row = page.getByRole('row', { name: new RegExp(address.slice(2, 8)) });
  await expect(row.getByText('Clear')).toBeVisible();
  await expect(row.getByText('Needs out-of-band check')).toBeVisible();

  await row.getByRole('button', { name: 'Record check' }).click();
  await page
    .getByLabel('Who confirmed it, and when?')
    .fill('Called the vendor CFO on the number on file');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Record check' })
    .click();
  await expect(row.getByText('Ready to register')).toBeVisible();

  await row.getByRole('button', { name: 'Register on-chain' }).click();
  await expect(page).toHaveURL(/\/governance\//);
  await expect(page.getByText('Awaiting signatures').first()).toBeVisible();
  const governanceUrl = page.url();

  // Only the Owner gets a sign action: an Operator opens the same transaction without one.
  const operator = await context.browser()!.newContext();
  const operatorPage = await operator.newPage();
  await loginAs(operatorPage, users.finance);
  await operatorPage.goto(governanceUrl);
  await expect(operatorPage.getByText('Register a payee').first()).toBeVisible();
  await expect(operatorPage.getByText('Only an Owner can sign this')).toBeVisible();
  await expect(
    operatorPage.getByRole('button', { name: 'Sign with wallet' }),
  ).toHaveCount(0);
  await operator.close();

  await connectWallet(page);
  await page.getByRole('button', { name: 'Sign with wallet' }).click();
  await page.getByRole('button', { name: 'Execute transaction' }).click();
  await expect(page.getByText('Executed on-chain').first()).toBeVisible();

  // The worker's event indexer moves the payee to Cooling from the PayeeAdded log.
  await tick();
  await page.goto(payeesUrl);
  await expect(row.getByText('Cooling period')).toBeVisible();

  // Time moves on Anvil, not on the wall clock.
  await advanceTime(24 * 3600);
  await tick();
  await page.goto(payeesUrl);
  await expect(row.getByText('Active', { exact: true })).toBeVisible();
});
