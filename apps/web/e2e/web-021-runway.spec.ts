import { expect, test } from '@playwright/test';

test('WEB-021 shows a runway chart per wallet and the suggested refills', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  // A full reload would reset the in-browser mock database.
  await page.getByRole('link', { name: 'Requests' }).click();
  await page.getByRole('link', { name: 'Overview' }).click();

  for (const wallet of ['Payments Safe', 'Payroll Safe']) {
    await expect(
      page.getByRole('img', {
        name: `${wallet} projected balance for the next 7 days`,
      }),
    ).toBeVisible();
  }
  await expect(
    page.getByRole('switch', { name: 'Include drafts' }),
  ).toBeVisible();
  await page.getByRole('switch', { name: 'Include drafts' }).click();
  await expect(
    page.getByRole('heading', { name: 'Payroll Safe runway' }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Suggested refills' }),
  ).toBeVisible();
});
