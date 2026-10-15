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
});
