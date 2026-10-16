import { expect, test } from '@playwright/test';

test('WEB-005 owner drafts a looser mandate, confirms it and hands off to governance', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  // A full reload would reset the in-browser mock database.
  await page.getByRole('link', { name: 'Mandate' }).first().click();

  const perRequest = page.locator('[id="limits.PAY.perRequest"]');
  await perRequest.fill('2500.5');
  await page.getByRole('button', { name: 'Save draft and preview' }).click();

  const create = page.getByRole('button', {
    name: 'Create governance transaction',
  });
  await expect(create).toBeDisabled();
  await page
    .getByRole('checkbox', { name: 'I understand this loosens the mandate' })
    .check();
  await create.click();
  await expect(page).toHaveURL(/\/governance\//);
  await expect(page.getByText('Awaiting signatures').first()).toBeVisible();
  await page.getByRole('link', { name: 'Mandate' }).first().click();
  await expect(page.getByText('Pending activation').first()).toBeVisible();
});

test('WEB-005 rejects a zero executor and keeps server errors visible', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  await page.getByRole('link', { name: 'Mandate' }).first().click();

  const save = page.getByRole('button', { name: 'Save draft and preview' });
  await page.locator('#executor').fill(`0x${'0'.repeat(40)}`);
  await save.click();
  await expect(
    page.getByText('Enter a valid, non-zero executor address.'),
  ).toBeVisible();

  await page.locator('#executor').fill(`0x${'1'.repeat(40)}`);
  await page.locator('[id="limits.PAY.perRequest"]').fill('999999999');
  await save.click();
  await expect(
    page.getByText('The PAY per-request limit exceeds its daily limit.'),
  ).toBeVisible();
});
