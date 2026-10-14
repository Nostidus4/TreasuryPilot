import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, test } from 'vitest';

import { db } from '@/mocks/db';
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

  expect(await screen.findByText('Partially completed')).toBeInTheDocument();
  expect(screen.getByText('Progress').parentElement).toHaveTextContent('1/3');
  const timeline = screen.getByRole('list', { name: /execution steps/i });
  expect(
    within(timeline).getByText('Paid · 3 confirmations'),
  ).toBeInTheDocument();
  expect(
    within(timeline).getByText(
      'Verification passed: amount and recipient match the plan',
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
  expect(
    within(timeline).getByRole('link', {
      name: 'Open transaction in the block explorer',
    }),
  ).toHaveAttribute(
    'href',
    `https://sepolia.etherscan.io/tx/${'b'.repeat(64)}`,
  );
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

test('selecting a Safe in one chart zooms the liquidity chart into it', async () => {
  const user = userEvent.setup();
  renderApp(T);

  const safes = (
    await screen.findByRole('heading', { name: 'Safes' })
  ).closest('section')!;
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

test('signing is blocked until high-risk flags are acknowledged, then the request is Approved', async () => {
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

  // Now the 13-field object appears and matches what the server built.
  expect(await screen.findByText('PaymentApproval')).toBeInTheDocument();
  expect(screen.getByText(/13 fields/i)).toBeInTheDocument();
  expect(screen.getByText('875000000')).toBeInTheDocument();

  await waitFor(() =>
    expect(
      screen.getByRole('button', { name: /sign approval/i }),
    ).toBeEnabled(),
  );
  await user.click(screen.getByRole('button', { name: /sign approval/i }));

  await waitFor(() =>
    expect(db.requests.find((item) => item.id === 'req_288')?.status).toBe(
      'Approved',
    ),
  );
  expect((await screen.findAllByText('Approved')).length).toBeGreaterThan(0);
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
    await screen.findAllByText('Paid · 3 confirmations', undefined, {
      timeout: 4000,
    }),
  ).toHaveLength(3);
  expect(await screen.findByText('All steps verified')).toBeInTheDocument();
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
