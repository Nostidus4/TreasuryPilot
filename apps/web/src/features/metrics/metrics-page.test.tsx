import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';

import type { OperationsMetrics } from '@/lib/api/types';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/render';

const series = [
  { date: '2026-10-13', paid: 2, volume: '1500000' },
  { date: '2026-10-14', paid: 3, volume: '2250000' },
];
const metrics: OperationsMetrics = {
  paymentsCount: 5,
  onTimeRate: 0.8,
  medianApprovalMinutes: 12,
  aiPlanRate: 0.6,
  exceptions: 1,
  unknownOperations: 0,
  completionRate: 0.9,
  interventionsPerRequest: 0.4,
  txCount: 7,
  fees: {
    totalWei: '3000000000000000',
    byStepType: { APPROVE: '1000000000000000', PAY: '2000000000000000' },
  },
  series,
};

test('rendered numbers match the API payload and every chart renders', async () => {
  server.use(
    http.get('*/v1/orgs/org_northwind/metrics/operations', () =>
      HttpResponse.json({ metrics }),
    ),
  );
  renderApp('/o/org_northwind/metrics');

  const tile = async (label: string) =>
    (await screen.findByText(label, { selector: 'p' })).parentElement!;
  expect(within(await tile('Payments executed')).getByText('5')).toBeVisible();
  expect(within(await tile('Paid on time')).getByText('80.0%')).toBeVisible();
  expect(
    within(await tile('Median time to approve')).getByText('12 min'),
  ).toBeVisible();
  expect(
    within(await tile('Plans from the AI planner')).getByText('60.0%'),
  ).toBeVisible();
  expect(
    within(await tile('Interventions per request')).getByText('0.40'),
  ).toBeVisible();

  const chart = (name: RegExp) => screen.getByRole('img', { name });
  const rates = chart(/completion rate and the on-time rate/).closest(
    'figure',
  )!;
  expect(within(rates).getByText('90.0%')).toBeInTheDocument();
  expect(within(rates).getByText('80.0%')).toBeInTheDocument();
  const fees = chart(/network fees paid/).closest('figure')!;
  expect(within(fees).getByText('0.001 ETH')).toBeInTheDocument();
  expect(within(fees).getByText('0.002 ETH')).toBeInTheDocument();
  expect(screen.getByText(/7 transactions, total 0.003 ETH/)).toBeVisible();
  const volume = chart(/payment volume executed/).closest('figure')!;
  expect(within(volume).getByText('1.50 USDC')).toBeInTheDocument();
  expect(within(volume).getByText('2.25 USDC')).toBeInTheDocument();
  expect(chart(/number of payments executed/)).toBeInTheDocument();
});
