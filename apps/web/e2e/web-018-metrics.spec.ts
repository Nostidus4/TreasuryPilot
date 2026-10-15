import { expect, test } from '@playwright/test';

test('WEB-018 metrics and savings pages render charts and API-backed numbers', async ({
  page,
}) => {
  await page.goto('/login');
  await page.getByLabel('Work email').fill('linh@northwind.test');
  await page.getByRole('button', { name: 'Send sign-in link' }).click();
  await page.getByRole('link', { name: 'Open the sign-in link' }).click();
  await page.getByRole('link', { name: 'Metrics' }).first().click();

  await expect(page.getByRole('heading', { name: 'Metrics' })).toBeVisible();
  const tile = (label: string) =>
    page.locator('div', { has: page.getByText(label, { exact: true }) }).last();
  await expect(tile('Payments executed')).toContainText('32');
  await expect(tile('Paid on time')).toContainText('96.9%');
  await expect(tile('Interventions per request')).toContainText('0.25');

  for (const name of [
    /completion rate and the on-time rate/,
    /fees paid, by transaction/,
    /network fees paid for each day/,
    /Completed per day/,
    /Interventions per day/,
    /payment volume executed/,
    /number of payments executed/,
  ]) {
    await expect(page.getByRole('img', { name })).toBeVisible();
  }

  await expect(page.getByText('Savings against baseline B1')).toBeVisible();
  const row = page.getByRole('row').filter({ hasText: 'OT-2026-220' });
  await expect(row).toContainText('310.00');
  await expect(row).toContainText('6.20');
});
