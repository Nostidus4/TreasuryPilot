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
      },
    ],
    alerts: [],
  };
  server.use(
    http.get('*/v1/orgs/org_northwind/treasuries/trs_main/forecast', () =>
      HttpResponse.json(forecast),
    ),
  );

  const charts = await screen.findAllByRole('img', {
    name: /projected balance for the next 7 days$/i,
  });
  expect(charts.map((chart) => chart.getAttribute('aria-label'))).toEqual([
    `${o1.label} projected balance for the next 7 days`,
    `${o2.label} projected balance for the next 7 days`,
  ]);

  const o1Table = within(charts[0].closest('figure')!).getByRole('table');
  expect(within(o1Table).getByText(/4,000\.00/)).toBeInTheDocument();
  expect(within(o1Table).getByText(/1,500\.00/)).toBeInTheDocument();

  expect(
    await screen.findByRole('heading', { name: 'Suggested refills' }),
  ).toBeInTheDocument();
  expect(screen.getByText('4,500.00')).toBeInTheDocument();
});
