import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, test } from 'vitest';

import { api } from '@/lib/api/http';
import type { Forecast } from '@/lib/api/types';
import { db } from '@/mocks/db';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/render';

const BASE = '/o/org_northwind';
const T = `${BASE}/t/trs_main`;

test('an unauthenticated visitor is sent to sign in, then back to the deep link', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/plans/pln_0421`, { signedIn: false });

  await user.type(
    await screen.findByLabelText(/work email/i),
    'linh@northwind.test',
  );
  await user.click(screen.getByRole('button', { name: /send sign-in link/i }));
  expect(
    await screen.findByRole('heading', { name: /check your email/i }),
  ).toBeInTheDocument();

  await user.click(
    screen.getByRole('link', { name: /open the sign-in link/i }),
  );
  expect(
    await screen.findByRole('heading', { name: /plan pln_0421/i }),
  ).toBeInTheDocument();
});

test('sign-in shows the API error for an invalid email', async () => {
  const user = userEvent.setup();
  renderApp('/login', { signedIn: false });

  await user.type(await screen.findByLabelText(/work email/i), 'not-an-email');
  await user.click(screen.getByRole('button', { name: /send sign-in link/i }));
  expect(await screen.findByRole('alert')).toHaveTextContent(
    /valid work email/i,
  );
});

test('an expired sign-in link explains itself', async () => {
  renderApp('/verify?token=expired', { signedIn: false });
  expect(
    await screen.findByRole('heading', { name: /link has expired/i }),
  ).toBeInTheDocument();
});

test('plan timeline shows partial completion, verification evidence and unknown safely', async () => {
  renderApp(`${T}/plans/pln_0421`);

  // renderApp resets the mock database, so set up execution evidence after it.
  const plan = db.plans.find((item) => item.id === 'pln_0421')!;
  plan.status = 'PartiallyCompleted';
  Object.assign(plan.steps[0], {
    status: 'Verified',
    confirmations: 3,
    verification: 'VERIFIED',
    txHash: `0x${'a'.repeat(64)}`,
  });
  Object.assign(plan.steps[1], {
    status: 'Unknown',
    txHash: `0x${'b'.repeat(64)}`,
  });
  plan.steps[2].status = 'Dropped';

  expect(
    await screen.findByText(/steps have matching module event fields/),
  ).toBeInTheDocument();
  expect(screen.getByText('Progress').parentElement).toHaveTextContent('1/3');
  const timeline = screen.getByRole('list', { name: /execution steps/i });
  expect(
    within(timeline).getByText(
      'Event matched checked fields · 3 confirmations',
    ),
  ).toBeInTheDocument();
  expect(
    within(timeline).getByText(
      'Refill event matches request, destination, and amount',
    ),
  ).toBeInTheDocument();
  expect(
    within(timeline).getByText(
      'Checking the chain — no new payment will be sent',
    ),
  ).toBeInTheDocument();
  expect(
    within(timeline).getByText('Dropped by the network'),
  ).toBeInTheDocument();
  const explorerLinks = await within(timeline).findAllByRole('link', {
    name: 'Open transaction in the block explorer',
  });
  expect(explorerLinks.map((link) => link.getAttribute('href'))).toContain(
    `https://sepolia.etherscan.io/tx/0x${'b'.repeat(64)}`,
  );
});

test('a swap-for-gas step is labelled as the test router', async () => {
  renderApp(`${T}/plans/pln_0421`);

  const plan = db.plans.find((item) => item.id === 'pln_0421')!;
  Object.assign(plan.steps[0], {
    kind: 'SWAP',
    title: 'Swap for gas (TEST ROUTER)',
    venue: 'TEST_ROUTER',
    minOut: '1000',
  });

  const timeline = await screen.findByRole('list', {
    name: /execution steps/i,
  });
  expect(await within(timeline).findByText('TEST ROUTER')).toBeInTheDocument();
  expect(within(timeline).getAllByText('TEST ROUTER')).toHaveLength(1);
});

test('a new user creates an organization and lands on the checklist', async () => {
  const user = userEvent.setup();
  renderApp('/verify?token=mock.new.person%40example.com', { signedIn: false });

  await user.type(
    await screen.findByLabelText(/organization name/i),
    'Acme Robotics',
  );
  await user.click(
    screen.getByRole('button', { name: /create organization/i }),
  );

  expect(
    await screen.findByRole('heading', { name: /set up acme robotics/i }),
  ).toBeInTheDocument();
  expect(await screen.findByText(/1 of 5 complete/i)).toBeInTheDocument();
  expect(screen.getByText(/set up a treasury/i)).toBeInTheDocument();
});

test('the dashboard shows the position with symbol, network and the TEST label', async () => {
  renderApp(T);

  const position = (
    await screen.findByRole('heading', { name: 'Liquidity' })
  ).closest('section')!;
  expect(await within(position).findByText('163,000.00')).toBeInTheDocument();
  expect(within(position).getAllByText('USDC').length).toBeGreaterThan(0);
  expect(within(position).getAllByText('Sepolia').length).toBeGreaterThan(0);
  expect(within(position).getAllByText('TEST').length).toBeGreaterThan(0);
  expect(within(position).getByText('Testnet rate')).toBeInTheDocument();
});

test('negative savings are rendered with their negative sign', async () => {
  server.use(
    http.get('*/v1/orgs/org_northwind/metrics/savings', () =>
      HttpResponse.json({
        totals: { baseline: '1000000', actual: '1100000', saved: '-100000' },
        perRequest: [
          {
            requestId: 'req_negative_savings',
            invoiceNumber: 'NEG-2026-001',
            vendorName: 'Negative Savings Vendor',
            baseline: '1000000',
            actual: '1100000',
            saved: '-100000',
          },
        ],
        skipped: 3,
        warnings: ['No accepted ETH reference price'],
        methodology: 'Actual payment exceeded the due-date baseline.',
      }),
    ),
  );
  renderApp(`${BASE}/metrics`);

  expect(
    await screen.findByText('Savings against baseline B1'),
  ).toBeInTheDocument();
  const savedTile = screen.getByText('Saved', { selector: 'p' }).parentElement!;
  expect(within(savedTile).getByText('-0.10')).toBeInTheDocument();
  const row = screen.getByText('NEG-2026-001').closest('tr')!;
  expect(within(row).getByText('1.00')).toBeInTheDocument();
  expect(within(row).getByText('1.10')).toBeInTheDocument();
  expect(within(row).getByText('-0.10')).toBeInTheDocument();
  expect(screen.getByText('Not compared: 3')).toBeInTheDocument();
  expect(
    screen.getByText('No accepted ETH reference price'),
  ).toBeInTheDocument();
});

test('the runway toggle requests the forecast with drafts enabled', async () => {
  const user = userEvent.setup();
  let includeDrafts: string | null = null;
  server.use(
    http.get(
      '*/v1/orgs/org_northwind/treasuries/trs_main/forecast',
      ({ request }) => {
        includeDrafts = new URL(request.url).searchParams.get('includeDrafts');
        return HttpResponse.json({
          days: [],
          wallets: [],
          suggestedRefills: [],
          alerts: [],
        });
      },
    ),
  );
  renderApp(T);

  const toggle = await screen.findByRole('switch', { name: 'Include drafts' });
  expect(toggle).not.toBeChecked();
  await user.click(toggle);
  await waitFor(() => expect(includeDrafts).toBe('true'));
});

test('the forecast mock adds draft outflow when requested', async () => {
  const dueDate = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000)
    .toISOString()
    .slice(0, 10);
  renderApp(T, {
    beforeRender: () => {
      const draft = db.requests.find((item) => item.id === 'req_090')!;
      draft.dueDate = `${dueDate}T12:00:00.000Z`;
    },
  });

  const draft = db.requests.find((item) => item.id === 'req_090')!;
  const path = '/orgs/org_northwind/treasuries/trs_main/forecast';
  const [withoutDrafts, withDrafts] = await Promise.all([
    api.get<Forecast>(path),
    api.get<Forecast>(`${path}?includeDrafts=true`),
  ]);
  const baseDay = withoutDrafts.days.find((day) => day.date === dueDate);
  const includedDay = withDrafts.days.find((day) => day.date === dueDate);

  expect(baseDay).toBeDefined();
  expect(includedDay).toBeDefined();
  expect(BigInt(includedDay!.outflow) - BigInt(baseDay!.outflow)).toBe(
    BigInt(draft.amount),
  );
});

test('the position card shows the reserve breakdown and what is available to supply', async () => {
  renderApp(T);

  const card = await screen.findByRole('group', { name: 'Position breakdown' });
  const rows = within(card);
  const row = (label: string) =>
    rows.getByText(label).closest('div')! as HTMLElement;
  expect(within(row('Safe USDC')).getByText('61,440.00')).toBeInTheDocument();
  expect(
    within(row('aUSDC (Aave)')).getByText('101,560.00'),
  ).toBeInTheDocument();
  expect(
    within(row('Payment reserve')).getByText('18,440.00'),
  ).toBeInTheDocument();
  expect(within(row('Floor')).getByText('5,000.00')).toBeInTheDocument();
  expect(within(row('Holds')).getByText('0.00')).toBeInTheDocument();
  expect(
    within(row('Required safe reserve')).getByText('23,440.00'),
  ).toBeInTheDocument();
  expect(
    within(row('Available for supply')).getByText('38,000.00'),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/no payment was due within 48 hours/i),
  ).toBeInTheDocument();
});

test('the organization view lists cross-chain treasuries separately without a combined balance', async () => {
  const user = userEvent.setup();
  renderApp(BASE, {
    beforeRender: () => {
      const second = structuredClone(db.treasuries.trs_main);
      second.treasury.id = 'trs_base';
      second.treasury.name = 'Base treasury';
      second.treasury.chainId = 84532;
      second.treasury.chainName = 'Base Sepolia';
      second.treasury.status = 'Active';
      second.treasury.asset = {
        ...second.treasury.asset,
        id: 'usdc-base-sepolia',
        address: `0x${'22'.repeat(20)}`,
      };
      second.mandate = {
        version: 7,
        status: 'Active',
        expiresAt: '2030-03-01T00:00:00.000Z',
      };
      second.budgets = [
        {
          action: 'PAY',
          usedToday: '42000000',
          dailyLimit: '100000000',
          perRequest: '20000000',
        },
      ];
      db.treasuries.trs_base = second;
      db.orgs[0].treasuries.push({ id: 'trs_base', name: 'Base treasury' });
    },
  });

  expect(await screen.findByText('2 treasuries')).toBeInTheDocument();
  expect(screen.getByText('Sepolia · USDC')).toBeInTheDocument();
  expect(screen.getByText('Base Sepolia · USDC')).toBeInTheDocument();
  expect(screen.queryByText('163,000.00')).not.toBeInTheDocument();
  const secondTreasuryLink = screen.getByRole('link', {
    name: /Base Sepolia · USDC/i,
  });
  expect(secondTreasuryLink).toHaveAttribute('href', `${BASE}/t/trs_base`);

  await user.click(secondTreasuryLink);
  expect(
    await screen.findByRole('heading', { name: 'Base treasury' }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole('heading', { name: 'Liquidity' }),
  ).toBeInTheDocument();
  expect(
    await screen.findByRole('group', { name: 'Position breakdown' }),
  ).toBeInTheDocument();
  expect(screen.getByText('v7')).toBeInTheDocument();
  expect(
    await screen.findByRole('meter', { name: 'Payments today' }),
  ).toHaveAttribute('aria-valuenow', '42');
  expect(
    screen.queryByRole('meter', { name: 'Refills today' }),
  ).not.toBeInTheDocument();
});

test('an organization without treasuries opens the setup checklist', async () => {
  renderApp(BASE, {
    beforeRender: () => {
      db.orgs[0].treasuries = [];
    },
  });

  expect(
    await screen.findByRole('heading', { name: /set up northwind/i }),
  ).toBeInTheDocument();
});

test('selecting a Safe in one chart zooms the liquidity chart into it', async () => {
  const user = userEvent.setup();
  renderApp(T);

  const safes = (await screen.findByRole('heading', { name: 'Safes' })).closest(
    'section',
  )!;
  const payroll = await within(safes).findByRole('button', {
    name: /payroll safe/i,
  });
  await user.click(payroll);

  expect(payroll).toHaveAttribute('aria-pressed', 'true');
  const level = screen.getByRole('navigation', { name: 'Liquidity level' });
  expect(within(level).getByText('Payroll Safe')).toBeInTheDocument();
});

test('a stale snapshot shows a banner', async () => {
  renderApp(T);
  await screen.findByRole('heading', { name: 'Liquidity' });
  db.treasuries.trs_main.staleness.stale = true;
  expect(
    await screen.findByText(/balances may be out of date/i),
  ).toBeInTheDocument();
});

test('signing is blocked until high-risk flags are acknowledged, then the request is planned', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/approvals/req_288`, { demoWallet: true });

  const sign = await screen.findByRole('button', { name: /sign approval/i });
  expect(sign).toBeDisabled();
  expect(
    screen.getByText(/signing is disabled until every high-risk flag/i),
  ).toBeInTheDocument();
  // The typed data is not even fetched before the flags are handled.
  expect(screen.queryByText('PaymentApproval')).not.toBeInTheDocument();

  await user.type(
    screen.getByLabelText(/why is it acceptable to proceed/i, {
      selector: '#ack-flg_288_payee',
    }),
    'Confirmed by phone with Northstar finance.',
  );
  await user.click(
    screen.getAllByRole('button', { name: /acknowledge flag/i })[0],
  );

  // Now the 14-field object appears and matches what the server built.
  expect(await screen.findByText('PaymentApproval')).toBeInTheDocument();
  expect(screen.getByText(/14 fields/i)).toBeInTheDocument();
  expect(screen.getByText('875000000')).toBeInTheDocument();

  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: /sign approval/i }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole('button', { name: /sign approval/i }));

  expect((await screen.findAllByText('Scheduled')).length).toBeGreaterThan(0);
  await waitFor(() =>
    expect(db.requests.find((item) => item.id === 'req_288')?.status).toBe(
      'Scheduled',
    ),
  );
  const request = db.requests.find((item) => item.id === 'req_288');
  expect(request?.planId).toBeTruthy();
  expect(
    db.plans.some((plan) =>
      plan.steps.some((step) => step.requestId === request?.id),
    ),
  ).toBe(true);
});

test('the creator of a request sees why they cannot approve it', async () => {
  renderApp(`${BASE}/approvals/req_033`, { demoWallet: true });

  expect(
    await screen.findByText(/you cannot approve this request/i),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/another approver must sign it/i),
  ).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: /sign approval/i }),
  ).not.toBeInTheDocument();
});

test('a possible duplicate is shown side by side with the earlier request', async () => {
  renderApp(`${BASE}/approvals/req_071`);

  expect(
    await screen.findByText(/possible duplicate of a paid invoice/i),
  ).toBeInTheDocument();
  expect(screen.getByText('This request')).toBeInTheDocument();
  expect(screen.getByText('Earlier request')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'HX-2026-070' })).toBeInTheDocument();
});

test('an owner signs a governance transaction, then executes it', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/governance/gov_030`, { demoWallet: true });

  expect(await screen.findByText(/1 of 2 signatures/i)).toBeInTheDocument();
  // The diff marks the change as loosening control.
  expect(screen.getAllByText('Looser').length).toBe(2);

  await user.click(screen.getByRole('button', { name: /sign with wallet/i }));
  expect(await screen.findByText(/2 of 2 signatures/i)).toBeInTheDocument();

  await user.click(
    await screen.findByRole('button', { name: /execute transaction/i }),
  );
  expect(
    await screen.findByText('Executed on-chain', { selector: 'p' }),
  ).toBeInTheDocument();

  // The effect is real: the new daily limit is active.
  await waitFor(() =>
    expect(db.treasuries.trs_main.budgets[0].dailyLimit).toBe('12000000000'),
  );
});

test('a delegatecall is called out and a failed transaction is explained', async () => {
  renderApp(`${BASE}/governance/gov_027`);

  expect(await screen.findByText('Delegatecall')).toBeInTheDocument();
  expect(screen.getByText(/runs another contract’s code/i)).toBeInTheDocument();
  expect(screen.getByText(/GS013/)).toBeInTheDocument();
});

test('a plan separates the policy decision from the AI explanation and runs to Paid', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/plans/pln_0421`);

  const policy = await screen.findByRole('region', { name: 'Policy decision' });
  const ai = screen.getByRole('complementary', { name: 'AI explanation' });
  expect(within(policy).getByText('WITHIN_DAILY_LIMIT')).toBeInTheDocument();
  expect(
    within(ai).getByText(/I scheduled Orbit Telecom early/i),
  ).toBeInTheDocument();
  expect(
    within(policy).queryByText(/I scheduled Orbit/i),
  ).not.toBeInTheDocument();
  expect(screen.getByText('AI planner')).toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: /run now/i }));

  expect(
    await screen.findAllByText(
      'Event matched checked fields · 3 confirmations',
      undefined,
      {
        timeout: 4000,
      },
    ),
  ).toHaveLength(3);
  expect(
    await screen.findByText('All checked module event fields match'),
  ).toBeInTheDocument();
  expect(db.requests.find((item) => item.id === 'req_219')?.status).toBe(
    'Paid',
  );
});

test('a rule-based plan shows its badge and says there is no AI text', async () => {
  renderApp(`${T}/plans/pln_0420`);

  expect(await screen.findByText('Rule-based')).toBeInTheDocument();
  expect(screen.getByText(/no ai explanation/i)).toBeInTheDocument();
});

test('an unknown outcome is never shown as failed', async () => {
  renderApp(`${T}/plans/pln_0419`);

  expect(
    await screen.findByText('Checking the chain — no new payment will be sent'),
  ).toBeInTheDocument();
  expect(screen.queryByText(/reverted on-chain/i)).not.toBeInTheDocument();
  expect(
    screen.getByText('Partially completed', { selector: 'p' }),
  ).toBeInTheDocument();
});

test('pausing asks for a reason and shows Pausing, then Paused on-chain', async () => {
  const user = userEvent.setup();
  renderApp(T);

  await user.click(await screen.findByRole('button', { name: 'Pause' }));
  const dialog = await screen.findByRole('dialog');
  expect(
    within(dialog).getByRole('button', { name: /pause treasury/i }),
  ).toBeDisabled();

  await user.type(
    within(dialog).getByLabelText(/reason/i),
    'Suspicious payee change',
  );
  await user.click(
    within(dialog).getByRole('button', { name: /pause treasury/i }),
  );

  expect(await within(dialog).findByText('Pausing…')).toBeInTheDocument();
  await user.click(within(dialog).getAllByRole('button', { name: 'Close' })[0]);

  expect(
    (await screen.findAllByText('Paused on-chain')).length,
  ).toBeGreaterThan(0);
  expect(
    await screen.findByRole('button', { name: /resume/i }),
  ).toBeInTheDocument();
});

test('an expired mandate stays visible and links Owners to review it', async () => {
  renderApp(T, {
    beforeRender: () => {
      db.treasuries.trs_main.mandate!.status = 'Expired';
    },
  });

  expect(await screen.findByText('Mandate expired')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Review mandate' })).toHaveAttribute(
    'href',
    `${T}/mandate`,
  );
  expect(
    screen.getByText(
      'The agent cannot run new plans until an Owner activates a current mandate.',
    ),
  ).toBeInTheDocument();
});

const outflow = (overrides: Record<string, unknown> = {}) => ({
  id: 'rev_outflow_x',
  version: 1,
  type: 'UNEXPECTED_OUTFLOW' as const,
  title: '',
  detail: '',
  status: 'Open' as const,
  createdAt: new Date().toISOString(),
  treasuryId: 'trs_main',
  roles: ['OWN' as const],
  actions: ['ACKNOWLEDGE' as const],
  ...overrides,
});

test('an open unexpected-outflow item for this treasury raises a banner linking to the queue', async () => {
  renderApp(T, {
    beforeRender: () => {
      db.reviewItems = db.reviewItems.filter((i) => i.id !== 'rev_outflow');
      db.reviewItems.push(outflow(), outflow({ id: 'rev_outflow_y' }));
    },
  });

  expect(await screen.findByText('Unexpected outflow')).toBeInTheDocument();
  expect(screen.getByText(/left the Treasury Safe/)).toBeInTheDocument();
  expect(screen.getByText(/1 more in the review queue/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Review' })).toHaveAttribute(
    'href',
    `${BASE}/review`,
  );
});

test.each([
  ['resolved', { status: 'Resolved' }],
  ['on another treasury', { treasuryId: 'trs_other' }],
])('an outflow item that is %s shows no banner', async (_name, overrides) => {
  renderApp(T, {
    beforeRender: () => {
      db.reviewItems = db.reviewItems.filter((i) => i.id !== 'rev_outflow');
      db.reviewItems.push(outflow(overrides));
    },
  });
  await screen.findByText('Pending transactions');
  expect(screen.queryByText(/left the Treasury Safe/)).not.toBeInTheDocument();
});

test('the dashboard lists sent-but-unconfirmed transactions of executing plans', async () => {
  renderApp(T, {
    beforeRender: () => {
      const plan = db.plans.find((item) => item.id === 'pln_0421')!;
      plan.status = 'Executing';
      Object.assign(plan.steps[0], {
        status: 'Pending',
        txHash: `0x${'ab'.repeat(32)}`,
      });
    },
  });

  expect(await screen.findByText('Pending transactions')).toBeInTheDocument();
  expect(
    await screen.findByText('Sent — waiting for the network'),
  ).toBeInTheDocument();
});

test('the pending transactions list is empty when nothing is executing', async () => {
  renderApp(T, {
    beforeRender: () => {
      db.plans.forEach((plan) => {
        if (plan.status === 'Executing') plan.status = 'Completed';
      });
    },
  });
  expect(await screen.findByText('Nothing pending')).toBeInTheDocument();
});

test('an executing plan with no submitted or pending steps shows the empty state', async () => {
  renderApp(T, {
    beforeRender: () => {
      const plan = db.plans.find((item) => item.id === 'pln_0421')!;
      plan.status = 'Executing';
      plan.steps.forEach((step) => {
        step.status = 'Confirmed';
      });
    },
  });
  expect(await screen.findByText('Nothing pending')).toBeInTheDocument();
});

test('the pending transactions list is capped at 10 plans with a link to plans', async () => {
  renderApp(T, {
    beforeRender: () => {
      const base = db.plans.find((item) => item.id === 'pln_0421')!;
      for (let i = 0; i < 12; i++)
        db.plans.push({ ...base, id: `pln_x${i}`, status: 'Executing' });
    },
  });
  const link = await screen.findByRole('link', { name: /2 more executing/ });
  expect(link).toHaveAttribute('href', `${T}/plans`);
});

test('a manual request validates the amount before it reaches the API', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/requests/new`);

  await user.type(
    await screen.findByLabelText(/invoice number/i),
    'AC-2026-200',
  );
  await user.type(screen.getByLabelText(/^amount/i), '12.1234567');
  await user.click(screen.getByRole('button', { name: /save draft/i }));

  expect(
    await screen.findByText(/6 decimal places at most/i),
  ).toBeInTheDocument();
  expect(
    screen.getByText(/choose a vendor/i, { selector: 'p' }),
  ).toBeInTheDocument();
  expect(db.requests.some((item) => item.invoiceNumber === 'AC-2026-200')).toBe(
    false,
  );
});

test('the requests list filters by status group', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/requests`);

  expect(await screen.findByText('AC-2026-104')).toBeInTheDocument();
  expect(screen.queryByText('HX-2026-070')).not.toBeInTheDocument();

  await user.click(screen.getByRole('button', { name: /^paid/i }));
  expect(await screen.findByText('HX-2026-070')).toBeInTheDocument();
  expect(screen.queryByText('AC-2026-104')).not.toBeInTheDocument();
});

test('reconciliation refuses to match a payment with incomplete evidence', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/reconciliation`);

  await user.click(
    await screen.findByRole('row', { name: /open payment AC-2026-096/i }),
  );
  const sheet = await screen.findByRole('dialog');
  expect(
    within(sheet).getByText(/evidence is incomplete/i),
  ).toBeInTheDocument();
  expect(
    within(sheet).getByRole('button', { name: /mark as matched/i }),
  ).toBeDisabled();
});

test('a non-Safe verification error is shown beside the affected wallet field', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/treasuries/new`);

  await user.click(await screen.findByRole('button', { name: /continue/i }));
  await user.type(
    await screen.findByLabelText(/treasury safe \(T\)/i),
    `0x${'1'.repeat(36)}dead`,
  );
  await user.type(
    screen.getByLabelText(/payments safe \(O1\)/i),
    `0x${'2'.repeat(36)}bb22`,
  );
  await user.click(
    screen.getByRole('button', { name: /check safes and continue/i }),
  );

  expect(
    await screen.findByText(/no safe contract was found at this address/i),
  ).toBeInTheDocument();
  expect(screen.getByLabelText(/treasury safe \(T\)/i)).toHaveAttribute(
    'aria-invalid',
    'true',
  );
});

test('the setup wizard clearly labels Sepolia and its supported asset as TEST', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/treasuries/new`);

  expect(await screen.findByText('Sepolia · TEST')).toBeInTheDocument();
  expect(screen.getByText('Test network')).toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /continue/i }));
  expect(await screen.findByText('USDC · TEST')).toBeInTheDocument();
});

test('the unsupported Guardian step stays pending and cannot finish setup', async () => {
  renderApp(`${BASE}/treasuries/new?t=trs_main`, {
    beforeRender: () => {
      window.sessionStorage.setItem(
        'treasurypilot.module-draft.trs_main',
        JSON.stringify({ guardian: `0x${'3'.repeat(40)}` }),
      );
    },
  });

  expect(
    await screen.findByRole('heading', { name: 'Guardian Safe' }),
  ).toBeInTheDocument();
  expect(
    await screen.findByText(/guardian setup pending/i),
  ).toBeInTheDocument();
  expect(
    screen.getByLabelText(
      /address included in module settings \(unverified\)/i,
    ),
  ).toHaveValue(`0x${'3'.repeat(40)}`);
  expect(
    screen.getByRole('button', {
      name: /finish setup — guardian verification required/i,
    }),
  ).toBeDisabled();
  expect(screen.getByText(/MDT-010/i)).toBeInTheDocument();
  expect(screen.getByText('Verification pending')).toBeInTheDocument();
});

test('a malformed stored guardian address is not shown as module settings', async () => {
  renderApp(`${BASE}/treasuries/new?t=trs_main`, {
    beforeRender: () => {
      window.sessionStorage.setItem(
        'treasurypilot.module-draft.trs_main',
        JSON.stringify({ guardian: 'not-an-address' }),
      );
    },
  });

  expect(
    await screen.findByText(/guardian setup pending/i),
  ).toBeInTheDocument();
  expect(
    screen.queryByLabelText(/address included in module settings/i),
  ).not.toBeInTheDocument();
});

test('module setup creates a governance transaction for each treasury Safe', async () => {
  const user = userEvent.setup();
  renderApp(`${BASE}/treasuries/new`, { demoWallet: true });

  await user.click(await screen.findByRole('button', { name: /continue/i }));
  await user.click(
    await screen.findByRole('button', { name: /use demo safes/i }),
  );
  await user.click(
    screen.getByRole('button', { name: /check safes and continue/i }),
  );
  await user.type(
    await screen.findByLabelText(/guardian address in module config/i),
    `0x${'3'.repeat(36)}cc33`,
  );
  await user.click(
    screen.getByRole('button', { name: /prepare module transactions/i }),
  );

  await waitFor(() => {
    expect(
      db.governance.filter(
        (tx) => tx.treasuryId !== 'trs_main' && tx.kind === 'DEPLOY_MODULE',
      ),
    ).toHaveLength(2);
  });
  expect(
    await screen.findByText(/Enable the TreasuryPilot module on O1/i),
  ).toBeInTheDocument();
  expect(
    screen.getByText('Guardian Safe verification is pending'),
  ).toBeInTheDocument();
  await user.click(
    screen.getAllByRole('button', { name: /sign with wallet/i })[0],
  );
  expect(
    await screen.findByRole('button', { name: /execute transaction/i }),
  ).toBeInTheDocument();
});

test('fee policy: owner accepts the proposal in two clicks and sees it in history', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/settings/fees`);

  expect(await screen.findByText(/90th percentile fee/i)).toBeInTheDocument();
  expect(screen.getByText(/plans per day/i)).toBeInTheDocument();
  await user.click(screen.getByRole('radio', { name: /fast/i }));
  await user.click(screen.getByRole('button', { name: /^accept$/i }));
  await waitFor(() => expect(db.feePolicy.history[0].by).toBe('You'));
  expect(db.feePolicy.active?.preset).toBe('FAST');
  expect(await screen.findByText('Preset Fast')).toBeInTheDocument();
});

test('fee policy: a held plan shows its fee and deadline and can be paid', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/settings/fees`);

  const banner = await screen.findByText(/is waiting on a network fee/i);
  const alert = banner.closest('[role="status"]') as HTMLElement;
  expect(alert).toHaveTextContent(/estimated fee 0\.0042 ETH/i);
  expect(alert).toHaveTextContent(/decide by/i);
  expect(within(alert).getByRole('button', { name: /defer/i })).toBeVisible();
  await user.click(
    within(alert).getByRole('button', { name: /pay now at 0\.0042 eth/i }),
  );
  await waitFor(() =>
    expect(screen.queryByText(/is waiting on a network fee/i)).toBeNull(),
  );
  expect(db.feePolicy.history[0].kind).toBe('PLAN_FEE');
});

test('fee policy: deferring keeps the plan held', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/settings/fees`);

  const banner = await screen.findByText(/is waiting on a network fee/i);
  const alert = banner.closest('[role="status"]') as HTMLElement;
  await user.click(within(alert).getByRole('button', { name: /defer/i }));
  await waitFor(() =>
    expect(within(alert).getByRole('button', { name: /defer/i })).toBeEnabled(),
  );
  expect(db.feeReviews).toHaveLength(1);
});

test('fee policy: an auditor sees the held plan without decision buttons', async () => {
  renderApp(`${T}/settings/fees`, {
    beforeRender: () => {
      db.members[0].roles = ['AUD'];
    },
  });

  const banner = await screen.findByText(/is waiting on a network fee/i);
  const alert = banner.closest('[role="status"]') as HTMLElement;
  expect(alert).toHaveTextContent(/only an owner, finance or operator/i);
  expect(within(alert).queryByRole('button')).toBeNull();
});

test('acting on a stale review item prompts a refresh and sends the version', async () => {
  const user = userEvent.setup();
  let posted: { version?: number } | undefined;
  server.use(
    http.post(
      '*/v1/orgs/:orgId/review-items/:id/actions',
      async ({ request }) => {
        posted = (await request.json()) as { version?: number };
        return HttpResponse.json(
          {
            type: 'about:blank',
            title: 'Conflict',
            status: 409,
            code: 'STALE_ITEM',
            detail: 'Reload the review item before acting.',
          },
          {
            status: 409,
            headers: { 'content-type': 'application/problem+json' },
          },
        );
      },
    ),
  );
  renderApp(`${BASE}/review?item=rev_unknown`);

  await user.type(await screen.findByLabelText('Note'), 'checked explorer');
  await user.click(screen.getByRole('button', { name: 'Confirm' }));

  expect(await screen.findByText('This item changed')).toBeInTheDocument();
  expect(posted?.version).toBe(1);
  expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument();
});

test('Refresh refetches the queue and clears the stale prompt', async () => {
  const user = userEvent.setup();
  let stale = true;
  let listCalls = 0;
  server.use(
    http.get('*/v1/orgs/:orgId/review-items', () => {
      listCalls += 1;
      return HttpResponse.json({ items: db.reviewItems });
    }),
    http.post('*/v1/orgs/:orgId/review-items/:id/actions', () =>
      stale
        ? HttpResponse.json(
            {
              type: 'about:blank',
              title: 'Conflict',
              status: 409,
              code: 'STALE_ITEM',
              detail: 'x',
            },
            {
              status: 409,
              headers: { 'content-type': 'application/problem+json' },
            },
          )
        : HttpResponse.json({ item: db.reviewItems[0] }),
    ),
  );
  renderApp(`${BASE}/review?item=rev_unknown`);

  await user.type(await screen.findByLabelText('Note'), 'checked explorer');
  await user.click(screen.getByRole('button', { name: 'Confirm' }));
  await screen.findByText('This item changed');
  const before = listCalls;
  stale = false;
  await user.click(screen.getByRole('button', { name: 'Refresh' }));

  await waitFor(() => expect(listCalls).toBeGreaterThan(before));
  await waitFor(() =>
    expect(screen.queryByText('This item changed')).not.toBeInTheDocument(),
  );
});

test('mock review action: 409 on version mismatch, 422 without version, no bump on 422', async () => {
  const path = '/v1/orgs/org_northwind/review-items/rev_unknown/actions';
  const post = (body: object) =>
    api.post(path.replace('/v1', ''), body).then(
      () => undefined,
      (error: { status?: number; code?: string }) => error,
    );
  renderApp(BASE);
  const item = db.reviewItems.find((entry) => entry.id === 'rev_unknown')!;
  expect(
    await post({ action: 'RETRY', note: 'x', version: item.version + 1 }),
  ).toMatchObject({ code: 'STALE_ITEM' });
  expect(await post({ action: 'RETRY', note: 'x' })).toMatchObject({
    code: 'VALIDATION',
  });
  const before = item.version;
  expect(
    await post({ action: 'RETRY', note: ' ', version: before }),
  ).toMatchObject({
    code: 'VALIDATION',
  });
  expect(item.version).toBe(before);
});

test('a mandate that failed read-back shows Discrepancy, and non-owners see pending as read-only', async () => {
  renderApp(`${T}/mandate`, {
    beforeRender: () => {
      const [active] = db.mandates.trs_main;
      db.mandates.trs_main = [
        { ...active, version: 9, status: 'Discrepancy' },
        { ...active, version: 8, status: 'PendingActivation' },
        ...db.mandates.trs_main,
      ];
    },
  });

  expect(
    await screen.findByText('v9 does not match the chain'),
  ).toBeInTheDocument();
  expect(screen.getAllByText('Discrepancy').length).toBeGreaterThan(0);
  expect(screen.getByText('v8 is waiting for signatures')).toBeInTheDocument();
});

test('mandate editor: the summary matches the saved base units, a looser change needs confirmation, and activation stays pending', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/mandate`);

  const field = await screen.findByLabelText('Per request', {
    selector: '#limits\\.PAY\\.perRequest',
  });
  await user.clear(field);
  await user.type(field, '2500.5');
  await user.click(screen.getByRole('button', { name: /save draft/i }));

  // The preview is built from the stored draft, so it equals what the API got.
  const draft = db.mandates.trs_main.find((item) => item.status === 'Draft')!;
  expect(draft.config.limits.PAY.perRequest).toBe('2500500000');
  expect(
    await screen.findByText(/A single payment can be at most 2,?500\.50 USDC/),
  ).toBeInTheDocument();
  expect(screen.getAllByText(/looser/i).length).toBeGreaterThan(0);

  const create = screen.getByRole('button', {
    name: 'Create governance transaction',
  });
  expect(create).toBeDisabled();
  await user.click(
    screen.getByRole('checkbox', {
      name: 'I understand this loosens the mandate',
    }),
  );
  await user.click(create);

  expect(
    (await screen.findAllByText(/activate mandate v\d+/i)).length,
  ).toBeGreaterThan(0);
  expect(
    db.mandates.trs_main.find((item) => item.version === draft.version)!.status,
  ).toBe('PendingActivation');
});

async function saveMandateDraft(
  user: ReturnType<typeof userEvent.setup>,
  values: Record<string, string>,
) {
  for (const [id, value] of Object.entries(values)) {
    const field = await screen.findByLabelText(/.*/, {
      selector: `[id="${id}"]`,
    });
    await user.clear(field);
    await user.type(field, value);
  }
  await user.click(screen.getByRole('button', { name: /save draft/i }));
  await screen.findByText(/Changes against the active mandate/);
}

const createTx = () =>
  screen.getByRole('button', { name: 'Create governance transaction' });
const confirmBox = () =>
  screen.queryByRole('checkbox', {
    name: 'I understand this loosens the mandate',
  });

test('mandate editor: a stricter-only change needs no confirmation', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/mandate`);
  await saveMandateDraft(user, { 'limits.PAY.perRequest': '1500' });

  expect(confirmBox()).not.toBeInTheDocument();
  expect(createTx()).toBeEnabled();
});

test('mandate editor: a mixed looser and stricter change is gated', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/mandate`);
  await saveMandateDraft(user, {
    'limits.PAY.perRequest': '1500',
    'limits.PAY.daily': '12000',
  });

  expect(confirmBox()).toBeInTheDocument();
  expect(createTx()).toBeDisabled();
  expect(
    screen.getByText('Confirm the looser change above to continue.'),
  ).toBeInTheDocument();
});

test('mandate editor: editing after confirming, or re-saving, resets the confirmation', async () => {
  const user = userEvent.setup();
  renderApp(`${T}/mandate`);
  await saveMandateDraft(user, { 'limits.PAY.perRequest': '2500' });

  await user.click(confirmBox()!);
  expect(createTx()).toBeEnabled();

  // Editing any field drops the preview; saving again needs a fresh confirmation.
  const field = screen.getByLabelText(/.*/, {
    selector: '[id="limits.PAY.perRequest"]',
  });
  await user.clear(field);
  await user.type(field, '2600');
  expect(confirmBox()).not.toBeInTheDocument();
  await user.click(screen.getByRole('button', { name: /save draft/i }));
  await screen.findByText(/Changes against the active mandate/);
  expect(confirmBox()).not.toBeChecked();
  expect(createTx()).toBeDisabled();

  // Re-saving without edits also resets a ticked box.
  await user.click(confirmBox()!);
  await user.click(screen.getByRole('button', { name: /save draft/i }));
  await screen.findByText(/Changes against the active mandate/);
  expect(confirmBox()).not.toBeChecked();
  expect(createTx()).toBeDisabled();
});

test('mandate editor is read-only for non-owners', async () => {
  renderApp(`${T}/mandate`, {
    beforeRender: () => {
      db.members[0].roles = ['OPR'];
    },
  });

  expect(await screen.findByText('View only')).toBeInTheDocument();
  expect(
    screen.queryByRole('button', { name: /save draft/i }),
  ).not.toBeInTheDocument();
  expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});
