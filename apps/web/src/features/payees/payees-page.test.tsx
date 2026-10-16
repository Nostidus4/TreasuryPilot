import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, test, vi } from 'vitest';

import { api } from '@/lib/api/http';
import type { Payee } from '@/lib/api/types';
import { clearScreening, db, oobPending, startCooling, tick } from '@/mocks/db';
import { renderApp } from '@/test/render';

const PAYEES = '/o/org_northwind/t/trs_main/payees';
const TREASURY = '/orgs/org_northwind/treasuries/trs_main';

afterEach(() => vi.useRealTimers());

const quanta = (patch: Partial<Payee>): Payee => ({
  id: 'pay_quanta',
  treasuryId: 'trs_main',
  vendorId: 'vnd_quanta',
  label: 'Freight wallet',
  address: `0x${'ab'.repeat(20)}`,
  status: 'Screening',
  screening: null,
  ...oobPending,
  registrationTxId: null,
  activeFrom: null,
  createdAt: new Date().toISOString(),
  ...patch,
});

const rowOf = async () =>
  (await screen.findByText('Quanta Freight')).closest('tr')!;

test.each([
  ['Screening', quanta({}), /Screening/, null],
  [
    'Cooling',
    quanta({
      status: 'Cooling',
      screening: clearScreening(new Date().toISOString()),
      activeFrom: new Date(Date.now() + 90 * 60_000).toISOString(),
    }),
    /Cooling period/,
    /Payable in\s*1h 29m/,
  ],
  [
    'Active',
    quanta({
      status: 'Active',
      screening: clearScreening(new Date().toISOString()),
      activeFrom: new Date(Date.now() - 60_000).toISOString(),
    }),
    /^Active$/,
    null,
  ],
])(
  'payee in %s state renders its badge and countdown',
  async (_n, payee, badge, chip) => {
    renderApp(PAYEES, { beforeRender: () => db.payees.unshift(payee) });
    const row = await rowOf();
    expect(within(row).getByText(badge)).toBeInTheDocument();
    if (chip) expect(row).toHaveTextContent(chip);
    else expect(within(row).queryByText(/Payable in/)).not.toBeInTheDocument();
  },
);

test('mock backend moves a proposed payee Screening, Cooling, Active', async () => {
  renderApp(PAYEES);
  await screen.findByText('Acurast Cloud');
  const address = `0x${'cd'.repeat(20)}`;
  const { payee } = await api.post<{ payee: Payee }>(`${TREASURY}/payees`, {
    vendorId: 'vnd_quanta',
    label: 'Freight',
    address,
  });
  expect(payee.status).toBe('Screening');
  expect(payee.screening).toBeNull();
  const state = async () =>
    (await api.get<{ items: Payee[] }>(`${TREASURY}/payees`)).items.find(
      (item) => item.id === payee.id,
    )!;
  expect((await state()).status).toBe('AwaitingOwner');
  await api.post(`${TREASURY}/payees/${payee.id}/verify-oob`, {
    method: 'PHONE',
    note: 'Called the CFO',
  });
  vi.useFakeTimers({ toFake: ['Date'] });
  db.timeScale = 1;
  startCooling(payee.id);
  expect(db.payees.find((item) => item.id === payee.id)!.status).toBe(
    'Cooling',
  );
  vi.setSystemTime(Date.now() + 61_000);
  tick();
  expect(db.payees.find((item) => item.id === payee.id)!.status).toBe('Active');
});

test('only the Owner sees the verify, register and deactivate actions', async () => {
  const awaiting = quanta({
    status: 'AwaitingOwner',
    screening: clearScreening(new Date().toISOString()),
  });
  renderApp(PAYEES, {
    beforeRender: () => {
      db.members[0].roles = ['OPR'];
      db.payees.unshift(awaiting);
    },
  });
  const row = await rowOf();
  // An Operator may propose, but cannot act on the payee.
  expect(screen.getByRole('button', { name: /propose payee/i })).toBeVisible();
  expect(
    within(row).queryByRole('button', {
      name: /record check|register|actions/i,
    }),
  ).toBeNull();
  expect(screen.queryByRole('button', { name: /actions for/i })).toBeNull();
});

test('Owner sees the verify action and records the check', async () => {
  const user = userEvent.setup();
  renderApp(PAYEES, {
    beforeRender: () =>
      db.payees.unshift(
        quanta({
          status: 'AwaitingOwner',
          screening: clearScreening(new Date().toISOString()),
        }),
      ),
  });
  const row = await rowOf();
  await user.click(within(row).getByRole('button', { name: 'Record check' }));
  await user.type(
    await screen.findByLabelText('Who confirmed it, and when?'),
    'Called the CFO',
  );
  await user.click(
    within(screen.getByRole('dialog')).getByRole('button', {
      name: 'Record check',
    }),
  );
  await waitFor(async () =>
    expect(
      within(await rowOf()).getByRole('button', { name: 'Register on-chain' }),
    ).toBeInTheDocument(),
  );
  expect(within(await rowOf()).getByText('Ready to register')).toBeVisible();
});

test('changing an address explains the new cooling period and queues the deactivation', async () => {
  const user = userEvent.setup();
  renderApp(PAYEES);
  const row = (await screen.findByText('Acurast Cloud')).closest('tr')!;
  await user.click(
    within(row).getByRole('button', { name: /actions for acurast cloud/i }),
  );
  await user.click(
    await screen.findByRole('menuitem', { name: /change address/i }),
  );
  const dialog = await screen.findByRole('dialog');
  expect(dialog).toHaveTextContent(/full cooling period/i);
  const next = `0x${'ef'.repeat(20)}`;
  await user.type(within(dialog).getByLabelText('New wallet address'), next);
  await user.type(within(dialog).getByLabelText('Reason'), 'Bank changed');
  await user.click(
    within(dialog).getByRole('button', {
      name: 'Create deactivation transaction',
    }),
  );
  await waitFor(() =>
    expect(db.payees.find((item) => item.address === next)?.status).toBe(
      'AwaitingOwner',
    ),
  );
  expect(
    db.governance.some((tx) => tx.title === 'Deactivate payee Acurast Cloud'),
  ).toBe(true);
});

test('a screening hit is an API error but the blocked payee appears in the list', async () => {
  const user = userEvent.setup();
  renderApp(PAYEES);
  await user.click(
    await screen.findByRole('button', { name: /^propose payee$/i }),
  );
  const dialog = await screen.findByRole('dialog');
  await user.click(within(dialog).getByRole('combobox'));
  await user.click(
    await screen.findByRole('option', { name: 'Quanta Freight' }),
  );
  await user.type(
    within(dialog).getByLabelText('Wallet address'),
    `0x${'1'.repeat(36)}dead`,
  );
  await user.click(
    within(dialog).getByRole('button', { name: 'Propose payee' }),
  );
  expect(
    await within(dialog).findByText(/sanctions screening list/i),
  ).toBeVisible();
  expect(await screen.findByText('Screening failed')).toBeVisible();
});
