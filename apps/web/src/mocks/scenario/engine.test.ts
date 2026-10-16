import { describe, expect, test } from 'vitest';

import {
  ActionError,
  allocation,
  apply,
  applyAll,
  approveInvoice,
  directorAction,
  economics,
  fixture,
  fundingPlan,
  initialState,
  ledgerStage,
  nextAuto,
  o1Breakdown,
  outcomeLines,
  pauseAgent,
  submitInvoice,
  submitSecurityInvoice,
  supplyPlan,
  tBreakdown,
  total,
  uploadInvoice,
  type DirectorAction,
  type ScenarioEvent,
  type ScenarioState,
} from './engine';

const e = (
  id: string,
  type: ScenarioEvent['type'],
  extra = {},
): ScenarioEvent => ({
  id,
  type,
  ...extra,
});

/** Runs every automatic transition (the hold at Outcome unknown stops it). */
function settle(state: ScenarioState): ScenarioState {
  let next = state;
  for (let guard = 0; guard < 40; guard += 1) {
    const step = nextAuto(next);
    if (!step) return next;
    next = applyAll(next, step.events);
  }
  throw new Error('playback did not settle');
}

const as = (state: ScenarioState, role: ScenarioState['role']) => ({
  ...state,
  role,
});

function run(state: ScenarioState, action: DirectorAction) {
  return settle(applyAll(state, directorAction(state, action).events));
}

/** Plays the full scenario to S5 through the same guards the product and Director use. */
function playToS5() {
  let s = initialState();
  s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
  s = applyAll(s, submitInvoice(s, true).events);
  s = as(s, 'APPROVER');
  s = settle(applyAll(s, approveInvoice(s).events));
  s = run(s, 'RELEASE_EXECUTION_WINDOW');
  s = run(s, 'RELEASE_PAY_VERIFICATION');
  s = run(s, 'LOAD_DAY_D_PLUS_ONE');
  s = run(s, 'RELEASE_SURPLUS_CYCLE');
  return s;
}

describe('derived values', () => {
  test('are computed from the fixture, not hard-coded', () => {
    const s0 = initialState();
    const plan = fundingPlan();
    expect(tBreakdown(s0).free).toBe(780_000_000n);
    expect(plan.o1Need).toBe(980_000_000n);
    expect(plan.tCapacity).toBe(780_000_000n);
    expect(plan.gap).toBe(200_000_000n);
    expect(plan.withdraw).toBe(210_000_000n);
    const econ = economics();
    expect(econ.discount).toBe(20_000_000n);
    // 980 * 4% * 7 / 365 = 0.7518 -> rounds to 0.75 for display, up to the next unit in base units.
    expect(econ.cashCost).toBe(751_781n);
    expect(econ.net).toBe(18_048_219n);
    expect(o1Breakdown(s0).spendable).toBe(0n);
  });

  test('S4 protects 1,100 and leaves a 1,310 surplus with 3,100 exposure', () => {
    let s = playToS5();
    // Rebuild S4 by replaying only up to the D+1 load.
    s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = settle(
      applyAll(as(s, 'APPROVER'), approveInvoice(as(s, 'APPROVER')).events),
    );
    s = run(s, 'RELEASE_EXECUTION_WINDOW');
    s = run(s, 'RELEASE_PAY_VERIFICATION');
    s = run(s, 'LOAD_DAY_D_PLUS_ONE');
    const alloc = allocation(s);
    expect(alloc.protectedTotal).toBe(1_100_000_000n);
    expect(alloc.surplus).toBe(1_310_000_000n);
    const plan = supplyPlan(s);
    expect(plan.amount).toBe(1_310_000_000n);
    expect(plan.exposureAfter).toBe(3_100_000_000n);
    expect(plan.eligible).toBe(true);
  });
});

describe('ledger S0 to S5', () => {
  test('every stage equals the fixture row and the total only moves with PAY and revenue', () => {
    let s = initialState();
    expect(ledgerStage(s)).toBe('S0');
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = as(s, 'APPROVER');
    s = settle(applyAll(s, approveInvoice(s).events));
    expect(s.invoiceA.status).toBe('READY_WAITING_WINDOW');
    expect(ledgerStage(s)).toBe('S0');

    s = applyAll(s, directorAction(s, 'RELEASE_EXECUTION_WINDOW').events);
    const stages: string[] = [];
    for (let i = 0; i < 20; i += 1) {
      const step = nextAuto(s);
      if (!step) break;
      s = applyAll(s, step.events);
      const stage = ledgerStage(s);
      if (stage && stages.at(-1) !== stage) stages.push(stage);
    }
    expect(stages).toEqual(['S0', 'S1', 'S2']);
    expect(ledgerStage(s)).toBe('S2');
    expect(s.invoiceA.status).toBe('OUTCOME_UNKNOWN');

    s = run(s, 'RELEASE_PAY_VERIFICATION');
    expect(ledgerStage(s)).toBe('S3');
    expect(total(s.ledger)).toBe(2_300_000_000n);

    s = run(s, 'LOAD_DAY_D_PLUS_ONE');
    expect(ledgerStage(s)).toBe('S4');
    s = run(s, 'RELEASE_SURPLUS_CYCLE');
    expect(ledgerStage(s)).toBe('S5');
    expect(total(s.ledger)).toBe(4_300_000_000n);
    expect(s.ledger.t).toBe('1100000000');
    expect(s.ledger.aave).toBe('3100000000');
  });

  test('holds and reserves follow the runbook table', () => {
    let s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = as(s, 'APPROVER');
    s = settle(applyAll(s, approveInvoice(s).events));
    s = applyAll(s, directorAction(s, 'RELEASE_EXECUTION_WINDOW').events);
    const seen: Record<string, ReturnType<typeof tBreakdown>> = {};
    while (nextAuto(s)) {
      s = applyAll(s, nextAuto(s)!.events);
      const stage = ledgerStage(s)!;
      seen[stage] = tBreakdown(s);
    }
    // S1: payroll 300 + floor 100 + funding hold 980 + uncommitted 10 = 1,390.
    expect(seen.S1.fundingHoldA).toBe(980_000_000n);
    expect(seen.S1.free).toBe(10_000_000n);
    // S2 and PAY unknown: T keeps 300 + 100 + 10; O1 holds 980 + buffer 100.
    expect(seen.S2.fundingHoldA).toBe(0n);
    expect(seen.S2.free).toBe(10_000_000n);
    expect(o1Breakdown(s).executionHold).toBe(980_000_000n);
    expect(s.invoiceA.lastVerifiedStage).toBe('S2');
  });
});

describe('idempotency and ordering', () => {
  test('replaying an event ID changes nothing', () => {
    let s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = as(s, 'APPROVER');
    s = settle(applyAll(s, approveInvoice(s).events));
    s = run(s, 'RELEASE_EXECUTION_WINDOW');
    const before = s.ledger;
    const again = applyAll(s, [
      e('evt-withdraw-confirmed', 'WITHDRAW_CONFIRMED'),
      e('evt-refill-confirmed', 'REFILL_CONFIRMED'),
    ]);
    expect(again).toBe(s);
    expect(again.ledger).toEqual(before);
    const verified = run(s, 'RELEASE_PAY_VERIFICATION');
    expect(apply(verified, e('evt-pay-verified', 'PAY_VERIFIED'))).toBe(
      verified,
    );
    // Even under a fresh ID, a second verification cannot count a second payment.
    const twice = apply(verified, e('evt-pay-verified-2', 'PAY_VERIFIED'));
    expect(twice.ledger).toEqual(verified.ledger);
    expect(twice.invoiceA.paymentCount).toBe(1);
  });

  test('revenue, C and supply apply once even when delivered twice', () => {
    const s5 = playToS5();
    const again = applyAll(s5, [
      e('evt-revenue-confirmed', 'REVENUE_CONFIRMED'),
      e('evt-c-approved', 'C_APPROVED'),
      e('evt-supply-submitted', 'SUPPLY_SUBMITTED', { amount: '1310000000' }),
      e('evt-supply-confirmed', 'SUPPLY_CONFIRMED'),
    ]);
    expect(again.ledger).toEqual(s5.ledger);
    expect(directorAction(s5, 'LOAD_DAY_D_PLUS_ONE').noop).toBe(true);
    expect(directorAction(s5, 'RELEASE_SURPLUS_CYCLE').noop).toBe(true);
  });

  test('an event that does not fit the state is ignored', () => {
    const s = initialState();
    expect(apply(s, e('x1', 'PAY_VERIFIED'))).toBe(s);
    expect(apply(s, e('x2', 'WITHDRAW_CONFIRMED'))).toBe(s);
    expect(apply(s, e('x3', 'SUPPLY_CONFIRMED'))).toBe(s);
  });

  test('A is created exactly once', () => {
    let s = initialState();
    s = applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events);
    const second = uploadInvoice(s, 'INV-CLOUD-042.pdf');
    expect(second.noop).toBe(true);
    expect(second.events).toEqual([]);
  });
});

describe('Outcome unknown', () => {
  test('is never Paid or Matched before verification, never retried, ledger stays S2', () => {
    let s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = as(s, 'APPROVER');
    s = settle(applyAll(s, approveInvoice(s).events));
    s = run(s, 'RELEASE_EXECUTION_WINDOW');
    expect(s.invoiceA.status).toBe('OUTCOME_UNKNOWN');
    expect(s.invoiceA.recon).toBe('PENDING_VERIFICATION');
    expect(ledgerStage(s)).toBe('S2');
    expect(s.invoiceA.paymentCount).toBe(0);
    expect(s.invoiceA.paySubmissions).toBe(1);
    expect(s.invoiceA.steps['step-pay-001'].reference).toBe('SIM-TX-PAY-001');
    // The hold means no automatic verification, however often playback is asked.
    expect(nextAuto(s)).toBeNull();
    expect(settle(s)).toBe(s);
    // A second PAY submission is impossible.
    expect(apply(s, e('evt-pay-submitted-again', 'PAY_SUBMITTED'))).toBe(s);
  });

  test('without the hold the same reference verifies by itself', () => {
    let s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    s = applyAll(s, submitInvoice(s, true).events);
    s = as(s, 'APPROVER');
    s = settle(applyAll(s, approveInvoice(s).events));
    s = { ...s, director: { ...s.director, holdPayUnknown: false } };
    s = run(s, 'RELEASE_EXECUTION_WINDOW');
    expect(s.invoiceA.status).toBe('PAID');
    expect(s.invoiceA.recon).toBe('MATCHED');
    expect(s.invoiceA.paySubmissions).toBe(1);
    expect(s.invoiceA.paymentCount).toBe(1);
  });
});

describe('security and pause never change the ledger', () => {
  test('X blocked: no approval, reserve, plan, payment or ledger change', () => {
    let s = as(playToS5(), 'FINANCE');
    s = run(s, 'LOAD_SECURITY_INBOX');
    const before = {
      ledger: s.ledger,
      stage: ledgerStage(s),
      t: tBreakdown(s),
    };
    expect(s.invoiceX.status).toBe('FLAGGED_REVIEW');
    s = applyAll(s, submitSecurityInvoice(s).events);
    expect(s.invoiceX).toMatchObject({
      status: 'BLOCKED_UNKNOWN_RECIPIENT',
      approvals: 0,
      reserves: 0,
      plans: 0,
      payments: 0,
    });
    expect(s.ledger).toEqual(before.ledger);
    expect(ledgerStage(s)).toBe('S5');
    expect(tBreakdown(s)).toEqual(before.t);
    expect(submitSecurityInvoice(s).noop).toBe(true);
  });

  test('pause goes Active, Pausing, Paused and leaves S5 untouched', () => {
    let s = as(playToS5(), 'OWNER');
    s = applyAll(s, pauseAgent(s).events);
    expect(s.agent.status).toBe('PAUSING');
    s = settle(s);
    expect(s.agent.status).toBe('PAUSED');
    expect(s.activity[0].text).toBe('Next agent cycle skipped: AGENT_PAUSED');
    expect(ledgerStage(s)).toBe('S5');
    expect(pauseAgent(s).noop).toBe(true);
  });

  test('outcome lines come from the S5 state', () => {
    let s = as(playToS5(), 'OWNER');
    s = settle(applyAll(s, pauseAgent(s).events));
    expect(outcomeLines(s)).toEqual([
      'Invoice A: paid 980 / matched',
      'Payroll and upcoming bill reserves preserved',
      'One payment / unknown outcome verified before completion',
      'Only 1,310 surplus supplied / agent now paused',
    ]);
  });
});

describe('guards and roles', () => {
  const fails = (fn: () => unknown, code: string) => {
    try {
      fn();
    } catch (error) {
      expect(error).toBeInstanceOf(ActionError);
      expect((error as ActionError).code).toBe(code);
      return;
    }
    throw new Error(`expected ${code}`);
  };

  test('only the demo invoice uploads', () => {
    fails(
      () => uploadInvoice(initialState(), 'other.pdf'),
      'DEMO_UNSUPPORTED_FILE',
    );
  });

  test('Finance cannot approve; An and Minh have their own rights', () => {
    let s = initialState();
    s = settle(applyAll(s, uploadInvoice(s, 'INV-CLOUD-042.pdf').events));
    fails(() => submitInvoice(s, false), 'NOT_VERIFIED');
    s = applyAll(s, submitInvoice(s, true).events);
    fails(() => approveInvoice(s), 'SELF_APPROVAL');
    fails(() => approveInvoice(as(s, 'OWNER')), 'FORBIDDEN');
    fails(() => pauseAgent(as(s, 'APPROVER')), 'FORBIDDEN');
    fails(() => pauseAgent(s), 'FORBIDDEN');
  });

  test('director actions fail out of order and succeed in order', () => {
    const s0 = initialState();
    fails(() => directorAction(s0, 'RELEASE_EXECUTION_WINDOW'), 'OUT_OF_ORDER');
    fails(() => directorAction(s0, 'RELEASE_PAY_VERIFICATION'), 'OUT_OF_ORDER');
    fails(() => directorAction(s0, 'LOAD_DAY_D_PLUS_ONE'), 'OUT_OF_ORDER');
    fails(() => directorAction(s0, 'RELEASE_SURPLUS_CYCLE'), 'OUT_OF_ORDER');
    fails(() => directorAction(s0, 'SHOW_OUTCOME_OVERLAY'), 'OUT_OF_ORDER');
    expect(directorAction(s0, 'LOAD_SECURITY_INBOX').events).toHaveLength(1);
    expect(directorAction(s0, 'HOLD_PAY_UNKNOWN').noop).toBe(true);
  });
});

describe('fixture as the single source', () => {
  test('ledger rows balance with the documented events', () => {
    expect(fixture.ledger.map((row) => row.id)).toEqual([
      'S0',
      'S1',
      'S2',
      'S3',
      'S4',
      'S5',
    ]);
    for (const row of fixture.ledger) {
      expect(
        BigInt(row.t) + BigInt(row.o1) + BigInt(row.o2) + BigInt(row.aave),
      ).toBe(BigInt(row.total));
    }
  });
});
