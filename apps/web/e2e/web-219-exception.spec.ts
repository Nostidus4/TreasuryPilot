import { expect, test } from '@playwright/test';

test('WEB-219 an Owner grants an over-cap exception and the review item closes', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  // A full reload would reset the in-browser mock database.
  await page.getByRole('link', { name: 'Review' }).first().click();
  await page
    .getByRole('complementary', { name: 'Review items' })
    .getByRole('link', { name: /Over per request limit/ })
    .click();

  await expect(page.getByText('OVER_PER_REQUEST_LIMIT')).toBeVisible();
  await page
    .getByRole('button', { name: 'Create governance transaction to grant' })
    .click();
  await expect(page.getByText(/grantException/)).toBeVisible();
});
