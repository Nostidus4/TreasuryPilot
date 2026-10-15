import { expect, test } from '@playwright/test';

test('WEB-006 owner proposes a payee, records the check and opens the registration tx', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  // A full reload would reset the in-browser mock database.
  await page.getByRole('link', { name: 'Payees' }).first().click();

  await page.getByRole('button', { name: 'Propose payee' }).first().click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Vendor').click();
  await page.getByRole('option', { name: 'Quanta Freight' }).click();
  await dialog.getByLabel('Wallet address').fill(`0x${'ab'.repeat(20)}`);
  await dialog.getByRole('button', { name: 'Propose payee' }).click();

  const row = page.getByRole('row', { name: /Quanta Freight/ });
  await expect(
    row.getByText('Screening', { exact: true }).first(),
  ).toBeVisible();
  await expect(row.getByText('Needs out-of-band check')).toBeVisible();

  await row.getByRole('button', { name: 'Record check' }).click();
  await page
    .getByLabel('Who confirmed it, and when?')
    .fill('Called the vendor CFO on the number on file');
  await page
    .getByRole('dialog')
    .getByRole('button', { name: 'Record check' })
    .click();

  await row.getByRole('button', { name: 'Register on-chain' }).click();
  await expect(page).toHaveURL(/\/governance\//);
  await expect(page.getByText('Awaiting signatures').first()).toBeVisible();
});
