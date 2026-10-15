import { screen, within } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';

import type { Forecast } from '@/lib/api/types';
import { db } from '@/mocks/db';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/render';

const T = '/o/org_northwind/t/trs_main';

test('renders one runway chart per wallet that matches the forecast, with suggested refills', async () => {
  renderApp(T);
  const [safeT, o1, o2] = db.treasuries.trs_main.wallets;
  const day = (date: string, balance: string) => ({ date, balance });
  const forecast: Forecast = {
    days: [],
    wallets: [
      {
        role: 'O1',
        label: o1.label,
        safeAddress: o1.safeAddress,
        buffer: '2000000000',
        days: [
          day('2099-01-01', '4000000000'),
          day('2099-01-02', '1500000000'),
        ],
      },
      {
        role: 'O2',
        label: o2.label,
        safeAddress: o2.safeAddress,
        buffer: '500000000',
        days: [
          day('2099-01-01', '1010000000'),
          day('2099-01-02', '1010000000'),
        ],
      },
    ],
    suggestedRefills: [
      {
        date: '2099-01-02',
        sourceAddress: safeT.safeAddress,
        targetAddress: o1.safeAddress,
        amount: '4500000000',
        requestId: 'req_1',
      },
    ],
    alerts: [],
  };
  server.use(
    http.get('*/v1/orgs/org_northwind/treasuries/trs_main/forecast', () =>
      HttpResponse.json(forecast),
    ),
  );

  // O1 is charted by the 7-day runway card, so only O2 gets its own chart.
  const chart = await screen.findByRole('img', {
    name: `${o2.label} projected balance for the next 7 days`,
  });
  const table = within(chart.closest('figure')!).getByRole('table');
  expect(within(table).getAllByText(/1,010\.00/)).toHaveLength(2);
  expect(
    screen.queryByRole('img', {
      name: `${o1.label} projected balance for the next 7 days`,
    }),
  ).not.toBeInTheDocument();

  const refills = (
    await screen.findByRole('heading', { name: 'Suggested refills' })
  ).closest('[class*="rounded-lg"]') as HTMLElement;
  expect(within(refills).getByText('4,500.00')).toBeInTheDocument();
});

test('says no refills are suggested when the forecast has none', async () => {
  renderApp(T);
  const o2 = db.treasuries.trs_main.wallets[2];
  server.use(
    http.get('*/v1/orgs/org_northwind/treasuries/trs_main/forecast', () =>
      HttpResponse.json({
        days: [],
        wallets: [
          {
            role: 'O2',
            label: o2.label,
            safeAddress: o2.safeAddress,
            buffer: '500000000',
            days: [{ date: '2099-01-01', balance: '1010000000' }],
          },
        ],
        suggestedRefills: [],
        alerts: [],
      } satisfies Forecast),
    ),
  );
  expect(await screen.findByText('No refills suggested')).toBeInTheDocument();
});
