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

  await expect(
    page.getByRole('img', {
      name: 'Payroll Safe projected balance for the next 7 days',
    }),
  ).toBeVisible();
  await expect(
    page.getByRole('heading', { name: 'Suggested refills' }),
  ).toBeVisible();

  const withDrafts = page.waitForResponse(
    (response) =>
      response.url().includes('/forecast') &&
      response.url().includes('includeDrafts=true'),
  );
  await page.getByRole('switch', { name: 'Include drafts' }).click();
  await withDrafts;
});
