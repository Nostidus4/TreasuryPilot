import { expect, test } from 'vitest';

import {
  CHECKPOINTS,
  U,
  earlyCashCost,
  earlyNetEstimate,
  fundingGap,
  initialState,
  reduce,
  replay,
  surplus,
  tCapacityForA,
  tHoldA,
  tUncommitted,
  usdRounded,
  withdrawAmount,
  type Event,
  type ScenarioState,
} from './scenario';

const ledger = (s: ScenarioState) =>
  [s.balances.t, s.balances.o1, s.balances.o2, s.balances.aave].map(
    (v) => v / U,
  );
const run = (...events: Event[]) => events.reduce(reduce, initialState());

test('derived values match runbook §6.3', () => {
  expect(tCapacityForA(initialState().balances)).toBe(780n * U);
  expect(fundingGap).toBe(200n * U);
  expect(withdrawAmount).toBe(210n * U);
  expect(usdRounded(earlyCashCost)).toBe('0.75');
  expect(usdRounded(earlyNetEstimate)).toBe('18.05');
});

test('checkpoints reproduce the S0–S5 ledger and holds', () => {
  const s0 = initialState();
  expect(ledger(s0)).toEqual([1180n, 100n, 0n, 2000n]);
  expect(tUncommitted(s0)).toBe(780n * U);

  const c = replay(1, [...CHECKPOINTS[0].events]);
  expect(c.a.status).toBe('READY_WAITING_WINDOW');
  expect(tHoldA(c)).toBe(780n * U);

  const s1 = reduce(
    reduce(
      reduce(reduce(c, { type: 'RELEASE_EXECUTION_WINDOW' }), {
        type: 'PREFLIGHT_PASSED',
      }),
      { type: 'WITHDRAW_SUBMITTED' },
    ),
    { type: 'WITHDRAW_CONFIRMED' },
  );
  expect(ledger(s1)).toEqual([1390n, 100n, 0n, 1790n]);
  expect(tUncommitted(s1)).toBe(10n * U);
  // Same event again is a no-op.
  expect(reduce(s1, { type: 'WITHDRAW_CONFIRMED' })).toBe(s1);

  const d = replay(1, [...CHECKPOINTS[1].events]);
  expect(ledger(d)).toEqual([410n, 100n, 0n, 1790n]);
  expect(d.a.recon).toBe('Matched');
  expect(d.a.paySubmissions).toBe(1);

  const e = replay(1, [...CHECKPOINTS[2].events]);
  expect(ledger(e)).toEqual([1100n, 100n, 0n, 3100n]);
  expect(surplus(e)).toBe(0n);

  const f = replay(1, [...CHECKPOINTS[3].events]);
  expect(ledger(f)).toEqual(ledger(e));
  expect(f.agent).toBe('PAUSED');
  expect(f.security.blocked).toBe(true);
});

test('UNKNOWN holds without a second payment until verified', () => {
  let s = replay(1, [
    ...CHECKPOINTS[0].events,
    { type: 'RELEASE_EXECUTION_WINDOW' },
  ]);
  expect(s.a.status).toBe('OUTCOME_UNKNOWN');
  expect(ledger(s)).toEqual([410n, 1080n, 0n, 1790n]);
  expect(s.a.recon).toBe('Pending verification');
  s = reduce(s, { type: 'PAY_SUBMITTED' });
  expect(s.a.paySubmissions).toBe(1);
});

test('Finance cannot approve its own request; surplus is 1,310 on D+1', () => {
  const s = run(
    { type: 'UPLOAD_A' },
    { type: 'EXTRACTION_DONE' },
    { type: 'SET_REVIEWED', value: true },
    { type: 'SUBMIT_A' },
    { type: 'APPROVE_A' },
  );
  expect(s.a.status).toBe('AWAITING_APPROVAL');
  const d1 = reduce(replay(1, [...CHECKPOINTS[1].events]), {
    type: 'LOAD_DAY_D_PLUS_ONE',
  });
  expect(surplus(d1)).toBe(1310n * U);
});
