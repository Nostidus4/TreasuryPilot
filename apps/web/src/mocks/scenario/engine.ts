/**
 * Demo scenario engine (docs/demo, runbook section 6): pure, event-sourced, no timers and no
 * storage. State changes only through `apply(state, event)`; an event ID that was already
 * applied is ignored, and an event that arrives out of order is ignored too, so replaying or
 * double-delivering an event never moves money twice. All money is integer base units
 * (USDC, 6 decimals) held as decimal strings in the state and computed with bigint.
 */
import { formatUnits } from '@/lib/money';

import rawFixture from '../../../../../docs/demo/TreasuryPilot_Demo_7m30_Fixture.json';

/** The fixture, typed by the contract the demo screens read (`features/demo/types`). */
export const fixture = rawFixture as unknown as DemoFixture;

import type {
  ActivityEntry,
  EventType,
  AgentStatus,
  DemoFixture,
  DemoRole,
  ExecutionStatus,
  FundingHold,
  InvoiceStatus,
  Ledger,
  LogEntry,
  Overlay,
  ReconStatus,
  ScenarioState,
  Step,
  StepId,
  StepState,
  SupplyStatus,
} from '@/features/demo/types';

export type {
  ActivityEntry,
  EventType,
  AgentStatus,
  DemoRole,
  ExecutionStatus,
  FundingHold,
  InvoiceStatus,
  Ledger,
  LogEntry,
  Overlay,
  ReconStatus,
  ScenarioState,
  Step,
  StepId,
  StepState,
  SupplyStatus,
};
export { STEP_IDS } from '@/features/demo/types';

export interface ScenarioEvent {
  id: string;
  type: EventType;
  /** Scenario clock after the event, when it moves time. */
  clock?: string;
  amount?: string;
  flag?: boolean;
  overlay?: Overlay;
  actor?: string;
}

/* ───────────── Fixture accessors ───────────── */

const big = (value: string | bigint) => BigInt(value);
const A = fixture.invoices[0];
const B = fixture.invoices[1];
const C = fixture.invoices[2];
const X = fixture.securityScenario;
const MANDATE = fixture.mandate;
const T_FLOOR = big(fixture.accounts[0].buffer);

export const ledgerRows = fixture.ledger;

/** D+1 revenue (S4 row of the fixture ledger: cumulativeRevenue). */
const REVENUE_AMOUNT = fixture.ledger[4].cumulativeRevenue;

const initialLedger = (): Ledger => ({
  t: fixture.accounts[0].initialBalance,
  o1: fixture.accounts[1].initialBalance,
  o2: fixture.accounts[2].initialBalance,
  aave: fixture.pool.initialSupplied,
  vendorPaid: '0',
  revenue: '0',
});

/** Scenario seconds between two playback events (deterministic, not wall-clock). */
const STEP_SECONDS = 5;

const addSeconds = (iso: string, seconds: number) =>
  new Date(new Date(iso).getTime() + seconds * 1000).toISOString();

export function initialState(runId = 1): ScenarioState {
  return {
    version: 1,
    scenarioId: fixture.scenarioId,
    runId,
    clock: fixture.clock.start,
    role: 'FINANCE',
    ledger: initialLedger(),
    cApproved: false,
    invoiceA: {
      status: 'ABSENT',
      execution: 'NOT_STARTED',
      recon: 'NONE',
      planReady: false,
      approvalReference: null,
      createdBy: null,
      approvedBy: null,
      revision: 1,
      steps: {
        'step-withdraw-001': { status: 'PLANNED', reference: null },
        'step-refill-001': { status: 'PLANNED', reference: null },
        'step-pay-001': { status: 'PLANNED', reference: null },
      },
      fundingHold: 'NONE',
      paySubmissions: 0,
      paymentCount: 0,
      lastVerifiedStage: 'S0',
    },
    supply: { status: 'NOT_READY', amount: null, reference: null },
    invoiceX: {
      present: false,
      status: 'NONE',
      approvals: 0,
      reserves: 0,
      plans: 0,
      payments: 0,
    },
    agent: { status: 'ACTIVE' },
    activity: [],
    director: {
      holdPayUnknown: true,
      windowReleased: false,
      dayPlusOne: false,
      securityLoaded: false,
      overlay: 'NONE',
    },
    applied: [],
    log: [],
  };
}

/* ───────────── Derived values (computed, never hard-coded) ───────────── */

export function ceilDiv(numerator: bigint, denominator: bigint): bigint {
  return (numerator + denominator - 1n) / denominator;
}

/** Ledger stage S0 to S5 when the ledger equals one of the fixture rows. */
export function ledgerStage(state: ScenarioState): string | null {
  const row = ledgerRows.find(
    (item) =>
      item.t === state.ledger.t &&
      item.o1 === state.ledger.o1 &&
      item.o2 === state.ledger.o2 &&
      item.aave === state.ledger.aave &&
      item.cumulativeVendorPaid === state.ledger.vendorPaid &&
      item.cumulativeRevenue === state.ledger.revenue,
  );
  return row?.id ?? null;
}

export const total = (ledger: Ledger): bigint =>
  big(ledger.t) + big(ledger.o1) + big(ledger.o2) + big(ledger.aave);

export interface TBreakdown {
  balance: bigint;
  payrollReserve: bigint;
  floor: bigint;
  /** C's reserve, after the D+1 approval. */
  upcomingBillReserve: bigint;
  /** A's funding hold while the withdrawn funds wait at T. */
  fundingHoldA: bigint;
  /** Everything at T that is neither reserved nor held. */
  free: bigint;
}

export function tBreakdown(state: ScenarioState): TBreakdown {
  const balance = big(state.ledger.t);
  const payrollReserve = big(B.amount);
  const upcomingBillReserve = state.cApproved ? big(C.amount) : 0n;
  const fundingHoldA =
    state.invoiceA.fundingHold === 'AT_T' ? big(A.earlyAmount) : 0n;
  const committed =
    payrollReserve + T_FLOOR + upcomingBillReserve + fundingHoldA;
  return {
    balance,
    payrollReserve,
    floor: T_FLOOR,
    upcomingBillReserve,
    fundingHoldA,
    free: balance > committed ? balance - committed : 0n,
  };
}

export interface O1Breakdown {
  balance: bigint;
  buffer: bigint;
  executionHold: bigint;
  spendable: bigint;
}

export function o1Breakdown(state: ScenarioState): O1Breakdown {
  const balance = big(state.ledger.o1);
  const buffer = big(fixture.accounts[1].buffer);
  const executionHold =
    state.invoiceA.fundingHold === 'AT_O1' ? big(A.earlyAmount) : 0n;
  const spendable = balance - buffer - executionHold;
  return {
    balance,
    buffer,
    executionHold,
    spendable: spendable > 0n ? spendable : 0n,
  };
}

export interface FundingPlan {
  /** What O1 must hold before PAY: early amount plus buffer, less what O1 already has at S0. */
  o1Need: bigint;
  /** T capacity for this invoice, excluding other obligations. */
  tCapacity: bigint;
  gap: bigint;
  marginBps: number;
  withdraw: bigint;
}

/** Planning inputs are the day-start (S0) balances, so the plan does not move while it runs. */
export function fundingPlan(): FundingPlan {
  const start = initialLedger();
  const early = big(A.earlyAmount);
  const o1Buffer = big(fixture.accounts[1].buffer);
  const o1Need = early + o1Buffer - big(start.o1);
  const tCapacity = big(start.t) - big(B.amount) - T_FLOOR;
  const gap = o1Need > tCapacity ? o1Need - tCapacity : 0n;
  const marginBps = MANDATE.withdrawMarginBps;
  const withdraw = ceilDiv(gap * BigInt(10_000 + marginBps), 10_000n);
  return { o1Need, tCapacity, gap, marginBps, withdraw };
}

export interface Economics {
  standard: bigint;
  early: bigint;
  discount: bigint;
  cashCost: bigint;
  feeAllowance: bigint;
  net: bigint;
}

export function economics(): Economics {
  const e = fixture.economics;
  const standard = big(A.standardAmount);
  const early = big(A.earlyAmount);
  const discount = standard - early;
  // Opportunity cost of paying early, rounded up so the estimate is never flattering.
  const cashCost = ceilDiv(
    early * BigInt(e.annualCashCostBps) * BigInt(e.earlyPaymentDays),
    10_000n * 365n,
  );
  const feeAllowance = big(e.earlyPaymentFeeEstimateInUsdc);
  return {
    standard,
    early,
    discount,
    cashCost,
    feeAllowance,
    net: discount - cashCost - feeAllowance,
  };
}

export interface Allocation {
  tBalance: bigint;
  payroll: bigint;
  upcomingBill: bigint;
  floor: bigint;
  protectedTotal: bigint;
  surplus: bigint;
}

export function allocation(state: ScenarioState): Allocation {
  const tBalance = big(state.ledger.t);
  const payroll = big(B.amount);
  const upcomingBill = state.cApproved ? big(C.amount) : 0n;
  const holds = tBreakdown(state).fundingHoldA;
  const protectedTotal = payroll + upcomingBill + T_FLOOR + holds;
  return {
    tBalance,
    payroll,
    upcomingBill,
    floor: T_FLOOR,
    protectedTotal,
    surplus: tBalance > protectedTotal ? tBalance - protectedTotal : 0n,
  };
}

export interface SupplyCheck {
  id: string;
  label: string;
  pass: boolean;
}

export interface SupplyPlan {
  amount: bigint;
  exposureAfter: bigint;
  exposureCap: bigint;
  checks: SupplyCheck[];
  eligible: boolean;
}

export function supplyPlan(state: ScenarioState): SupplyPlan {
  const { surplus } = allocation(state);
  const exposureAfter = big(state.ledger.aave) + surplus;
  const cap = big(MANDATE.maxPoolExposure);
  const checks: SupplyCheck[] = [
    {
      id: 'reserves',
      label: 'Payroll, upcoming bill and floor reserves preserved',
      pass: surplus > 0n,
    },
    {
      id: 'min',
      label: 'At least the minimum supply amount',
      pass: surplus >= big(MANDATE.minSupplyAmount),
    },
    {
      id: 'per-tx',
      label: 'Within the SUPPLY per-transaction cap',
      pass: surplus <= big(MANDATE.supplyPerTx),
    },
    {
      id: 'daily',
      label: 'Within the SUPPLY daily cap',
      pass: surplus <= big(MANDATE.supplyDaily),
    },
    {
      id: 'exposure',
      label: 'Pool exposure stays under the mandate cap',
      pass: exposureAfter <= cap,
    },
    {
      id: 'resupply',
      label: 'No same-UTC-day re-supply after a withdraw',
      pass: state.director.dayPlusOne || state.invoiceA.fundingHold === 'NONE',
    },
    {
      id: 'pool',
      label: 'Pool enabled, health check passes, no treasury debt',
      pass: fixture.pool.enabled && !fixture.pool.hasTreasuryDebt,
    },
    {
      id: 'economics',
      label: 'Fee and risk economic check (synthetic assumption)',
      pass: fixture.economics.supplyFeeRiskEconomicCheck.startsWith('PASS'),
    },
  ];
  return {
    amount: surplus,
    exposureAfter,
    exposureCap: cap,
    checks,
    eligible: checks.every((check) => check.pass),
  };
}

/* ───────────── Reducers ───────────── */

const withLog = (
  state: ScenarioState,
  event: ScenarioEvent,
  clock: string,
): ScenarioState => ({
  ...state,
  clock,
  applied: [...state.applied, event.id],
  log: [...state.log, { id: event.id, type: event.type, at: clock }],
});

const activity = (state: ScenarioState, id: string, text: string) => ({
  ...state,
  activity: [{ id, at: state.clock, text }, ...state.activity],
});

const setStep = (
  state: ScenarioState,
  step: StepId,
  status: StepState,
  reference?: string,
): ScenarioState => ({
  ...state,
  invoiceA: {
    ...state.invoiceA,
    steps: {
      ...state.invoiceA.steps,
      [step]: {
        status,
        reference: reference ?? state.invoiceA.steps[step].reference,
      },
    },
  },
});

const stepIs = (state: ScenarioState, step: StepId, status: StepState) =>
  state.invoiceA.steps[step].status === status;

const sub = (value: string, amount: string) =>
  (big(value) - big(amount)).toString();
const add = (value: string, amount: string) =>
  (big(value) + big(amount)).toString();

/**
 * Applies one event. Returns the same object when the event ID was already applied or the
 * event does not fit the current state (idempotent and order-safe).
 */
export function apply(
  state: ScenarioState,
  event: ScenarioEvent,
): ScenarioState {
  if (state.applied.includes(event.id)) return state;
  const a = state.invoiceA;
  const tick = (seconds = STEP_SECONDS) =>
    event.clock ?? addSeconds(state.clock, seconds);
  const reducer = (next: ScenarioState, clock = tick()) =>
    withLog(next, event, clock);

  switch (event.type) {
    case 'UPLOAD_ACCEPTED': {
      if (a.status !== 'ABSENT') return state;
      return reducer({
        ...state,
        invoiceA: {
          ...a,
          status: 'EXTRACTING',
          createdBy: fixture.invoices[0].createdBy,
        },
      });
    }
    case 'EXTRACTION_DONE':
      if (a.status !== 'EXTRACTING') return state;
      return reducer({ ...state, invoiceA: { ...a, status: 'DRAFT' } });
    case 'SUBMITTED_FOR_APPROVAL':
      if (a.status !== 'DRAFT') return state;
      return reducer({
        ...state,
        invoiceA: { ...a, status: 'AWAITING_APPROVAL' },
      });
    case 'APPROVAL_GRANTED':
      if (a.status !== 'AWAITING_APPROVAL') return state;
      return reducer(
        {
          ...state,
          invoiceA: {
            ...a,
            status: 'APPROVED',
            approvalReference: A.approvalReference,
            approvedBy: A.approvedBy,
          },
        },
        fixture.clock.invoiceApprovalAt,
      );
    case 'PLAN_READY':
      if (a.status !== 'APPROVED') return state;
      return reducer(
        {
          ...state,
          invoiceA: { ...a, status: 'READY_WAITING_WINDOW', planReady: true },
        },
        fixture.clock.planReadyAt,
      );
    case 'WINDOW_RELEASED': {
      if (a.status !== 'READY_WAITING_WINDOW') return state;
      return reducer(
        {
          ...state,
          director: { ...state.director, windowReleased: true },
          invoiceA: { ...a, status: 'EXECUTING', execution: 'PREFLIGHT' },
        },
        fixture.clock.executionWindowOpensAt,
      );
    }
    case 'PREFLIGHT_PASSED':
      if (a.execution !== 'PREFLIGHT') return state;
      return reducer({ ...state, invoiceA: { ...a, execution: 'RUNNING' } });
    case 'WITHDRAW_SUBMITTED':
      if (
        a.execution !== 'RUNNING' ||
        !stepIs(state, 'step-withdraw-001', 'PLANNED')
      )
        return state;
      return reducer(
        setStep(
          state,
          'step-withdraw-001',
          'SUBMITTED',
          fixture.mockEvidence.withdrawReference,
        ),
      );
    case 'WITHDRAW_CONFIRMED': {
      if (!stepIs(state, 'step-withdraw-001', 'SUBMITTED')) return state;
      const amount = fundingPlan().withdraw.toString();
      const next = setStep(state, 'step-withdraw-001', 'CONFIRMED');
      return reducer({
        ...next,
        ledger: {
          ...next.ledger,
          t: add(next.ledger.t, amount),
          aave: sub(next.ledger.aave, amount),
        },
        invoiceA: {
          ...next.invoiceA,
          fundingHold: 'AT_T',
          lastVerifiedStage: 'S1',
        },
      });
    }
    case 'REFILL_SUBMITTED':
      if (
        !stepIs(state, 'step-withdraw-001', 'CONFIRMED') ||
        !stepIs(state, 'step-refill-001', 'PLANNED')
      )
        return state;
      return reducer(
        setStep(
          state,
          'step-refill-001',
          'SUBMITTED',
          fixture.mockEvidence.refillReference,
        ),
      );
    case 'REFILL_CONFIRMED': {
      if (!stepIs(state, 'step-refill-001', 'SUBMITTED')) return state;
      const amount = A.earlyAmount;
      const next = setStep(state, 'step-refill-001', 'CONFIRMED');
      return reducer({
        ...next,
        ledger: {
          ...next.ledger,
          t: sub(next.ledger.t, amount),
          o1: add(next.ledger.o1, amount),
        },
        invoiceA: {
          ...next.invoiceA,
          fundingHold: 'AT_O1',
          lastVerifiedStage: 'S2',
        },
      });
    }
    case 'PAY_SUBMITTED': {
      if (
        !stepIs(state, 'step-refill-001', 'CONFIRMED') ||
        !stepIs(state, 'step-pay-001', 'PLANNED')
      )
        return state;
      const next = setStep(
        state,
        'step-pay-001',
        'SUBMITTED',
        fixture.mockEvidence.payReference,
      );
      // Submitted, not settled: the ledger does not change.
      return reducer({
        ...next,
        invoiceA: {
          ...next.invoiceA,
          status: 'PAYMENT_SUBMITTED',
          paySubmissions: next.invoiceA.paySubmissions + 1,
        },
      });
    }
    case 'ACK_TIMEOUT': {
      if (a.status !== 'PAYMENT_SUBMITTED') return state;
      // The RPC acknowledgement was lost. Same reference, no retry, ledger untouched.
      const next = setStep(state, 'step-pay-001', 'OUTCOME_UNKNOWN');
      return activity(
        reducer({
          ...next,
          invoiceA: {
            ...next.invoiceA,
            status: 'OUTCOME_UNKNOWN',
            execution: 'OUTCOME_UNKNOWN',
            recon: 'PENDING_VERIFICATION',
          },
        }),
        `act-${event.id}`,
        `PAY outcome unknown: verifying ${fixture.mockEvidence.payReference}`,
      );
    }
    case 'PAY_VERIFIED': {
      // Only an unknown (or just-submitted) PAY can verify, and only once.
      if (a.status !== 'OUTCOME_UNKNOWN' && a.status !== 'PAYMENT_SUBMITTED')
        return state;
      if (a.paymentCount >= 1) return state;
      const amount = A.earlyAmount;
      const next = setStep(state, 'step-pay-001', 'CONFIRMED');
      return reducer({
        ...next,
        ledger: {
          ...next.ledger,
          o1: sub(next.ledger.o1, amount),
          vendorPaid: add(next.ledger.vendorPaid, amount),
        },
        invoiceA: {
          ...next.invoiceA,
          status: 'PAID',
          execution: 'COMPLETED',
          recon: 'MATCHING',
          fundingHold: 'RELEASED',
          paymentCount: next.invoiceA.paymentCount + 1,
          lastVerifiedStage: 'S3',
        },
      });
    }
    case 'RECON_MATCHED':
      if (a.status !== 'PAID' || a.recon !== 'MATCHING') return state;
      return reducer({ ...state, invoiceA: { ...a, recon: 'MATCHED' } });
    case 'HOLD_SET':
      return reducer(
        {
          ...state,
          director: { ...state.director, holdPayUnknown: event.flag ?? true },
        },
        state.clock,
      );
    case 'DAY_ADVANCED':
      if (state.director.dayPlusOne) return state;
      return reducer(
        { ...state, director: { ...state.director, dayPlusOne: true } },
        event.clock ?? fixture.clock.nextDay,
      );
    case 'REVENUE_CONFIRMED':
      return reducer(
        {
          ...state,
          ledger: {
            ...state.ledger,
            t: add(state.ledger.t, REVENUE_AMOUNT),
            revenue: add(state.ledger.revenue, REVENUE_AMOUNT),
          },
        },
        state.clock,
      );
    case 'C_APPROVED':
      return reducer({ ...state, cApproved: true }, state.clock);
    case 'SUPPLY_SUBMITTED': {
      if (
        state.supply.status === 'SUBMITTED' ||
        state.supply.status === 'CONFIRMED'
      )
        return state;
      return reducer(
        {
          ...state,
          supply: {
            status: 'SUBMITTED',
            amount: event.amount ?? '0',
            reference: fixture.mockEvidence.supplyReference,
          },
        },
        event.clock ?? fixture.clock.nextDaySupplyCycleOpensAt,
      );
    }
    case 'SUPPLY_CONFIRMED': {
      if (state.supply.status !== 'SUBMITTED' || !state.supply.amount)
        return state;
      const amount = state.supply.amount;
      return reducer({
        ...state,
        ledger: {
          ...state.ledger,
          t: sub(state.ledger.t, amount),
          aave: add(state.ledger.aave, amount),
        },
        supply: { ...state.supply, status: 'CONFIRMED' },
      });
    }
    case 'SECURITY_INBOX_LOADED':
      return reducer(
        {
          ...state,
          director: { ...state.director, securityLoaded: true },
          invoiceX: {
            ...state.invoiceX,
            present: true,
            status: 'FLAGGED_REVIEW',
          },
        },
        state.clock,
      );
    case 'UNKNOWN_RECIPIENT_BLOCKED':
      if (state.invoiceX.status !== 'FLAGGED_REVIEW') return state;
      // Blocked in the app: no approval, reserve, plan, payment or ledger change.
      return activity(
        reducer(
          {
            ...state,
            invoiceX: {
              ...state.invoiceX,
              status: 'BLOCKED_UNKNOWN_RECIPIENT',
            },
          },
          state.clock,
        ),
        `act-${event.id}`,
        `${X.number} blocked: ${X.expectedOnSubmit}`,
      );
    case 'AGENT_PAUSE_REQUESTED':
      if (state.agent.status !== 'ACTIVE') return state;
      return reducer({ ...state, agent: { status: 'PAUSING' } }, state.clock);
    case 'AGENT_PAUSED':
      if (state.agent.status !== 'PAUSING') return state;
      return activity(
        reducer({ ...state, agent: { status: 'PAUSED' } }, state.clock),
        `act-${event.id}`,
        'Next agent cycle skipped: AGENT_PAUSED',
      );
    case 'OVERLAY_SET':
      return reducer(
        {
          ...state,
          director: { ...state.director, overlay: event.overlay ?? 'NONE' },
        },
        state.clock,
      );
    default:
      return state;
  }
}

export function applyAll(
  state: ScenarioState,
  events: ScenarioEvent[],
): ScenarioState {
  return events.reduce(apply, state);
}

/* ───────────── Playback (what happens next without a click) ───────────── */

export const DELAYS_MS = {
  extract: 2500,
  planReady: 1500,
  step: 3000,
  recon: 3000,
  pause: 3000,
} as const;

export interface AutoStep {
  delayMs: number;
  events: ScenarioEvent[];
}

const ev = (
  id: string,
  type: EventType,
  extra: Partial<ScenarioEvent> = {},
): ScenarioEvent => ({
  id,
  type,
  ...extra,
});

/**
 * The next automatic transition, or null when the scenario is waiting for a person or the
 * Director (including the hold at Outcome unknown).
 */
export function nextAuto(state: ScenarioState): AutoStep | null {
  const a = state.invoiceA;
  const step = (type: EventType, id: string): AutoStep => ({
    delayMs: DELAYS_MS.step,
    events: [ev(id, type)],
  });
  if (a.status === 'EXTRACTING')
    return {
      delayMs: DELAYS_MS.extract,
      events: [ev('evt-extraction-done', 'EXTRACTION_DONE')],
    };
  if (a.status === 'APPROVED')
    return {
      delayMs: DELAYS_MS.planReady,
      events: [ev('evt-plan-ready', 'PLAN_READY')],
    };
  if (a.execution === 'PREFLIGHT')
    return step('PREFLIGHT_PASSED', 'evt-preflight-passed');
  if (a.execution === 'RUNNING') {
    const s = a.steps;
    if (s['step-withdraw-001'].status === 'PLANNED')
      return step('WITHDRAW_SUBMITTED', 'evt-withdraw-submitted');
    if (s['step-withdraw-001'].status === 'SUBMITTED')
      return step('WITHDRAW_CONFIRMED', 'evt-withdraw-confirmed');
    if (s['step-refill-001'].status === 'PLANNED')
      return step('REFILL_SUBMITTED', 'evt-refill-submitted');
    if (s['step-refill-001'].status === 'SUBMITTED')
      return step('REFILL_CONFIRMED', 'evt-refill-confirmed');
    if (s['step-pay-001'].status === 'PLANNED')
      return step('PAY_SUBMITTED', 'evt-pay-submitted');
  }
  if (a.status === 'PAYMENT_SUBMITTED')
    return step('ACK_TIMEOUT', 'evt-ack-timeout');
  // Without a hold the same reference verifies by itself; with the hold it waits for the Director.
  if (a.status === 'OUTCOME_UNKNOWN' && !state.director.holdPayUnknown)
    return step('PAY_VERIFIED', 'evt-pay-verified');
  if (a.status === 'PAID' && a.recon === 'MATCHING')
    return {
      delayMs: DELAYS_MS.recon,
      events: [ev('evt-recon-matched', 'RECON_MATCHED')],
    };
  if (state.supply.status === 'SUBMITTED')
    return step('SUPPLY_CONFIRMED', 'evt-supply-confirmed');
  if (state.agent.status === 'PAUSING')
    return {
      delayMs: DELAYS_MS.pause,
      events: [ev('evt-agent-paused', 'AGENT_PAUSED')],
    };
  return null;
}

/* ───────────── Actions (guards + the events they produce) ───────────── */

export class ActionError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly status = 409,
  ) {
    super(message);
  }
}

export interface ActionResult {
  events: ScenarioEvent[];
  /** The request changed nothing because the target state already holds. */
  noop?: boolean;
  message?: string;
}

const fail = (code: string, message: string, status = 409): never => {
  throw new ActionError(code, message, status);
};

const DEMO_FILE = fixture.documents[0].fileName;

export function uploadInvoice(
  state: ScenarioState,
  fileName: string,
): ActionResult {
  if (state.role !== 'FINANCE')
    fail('FORBIDDEN', 'Only Finance (Linh) uploads invoices.', 403);
  if (fileName !== DEMO_FILE)
    fail(
      'DEMO_UNSUPPORTED_FILE',
      `Unsupported in demo mode: only ${DEMO_FILE} can be uploaded.`,
      422,
    );
  // The request is created exactly once.
  if (state.invoiceA.status !== 'ABSENT')
    return { events: [], noop: true, message: 'Invoice A already exists.' };
  return { events: [ev('evt-upload-accepted', 'UPLOAD_ACCEPTED')] };
}

export function submitInvoice(
  state: ScenarioState,
  verified: boolean,
): ActionResult {
  if (state.role !== 'FINANCE')
    fail(
      'FORBIDDEN',
      'Only Finance (Linh) submits an invoice for approval.',
      403,
    );
  const a = state.invoiceA;
  if (a.status === 'ABSENT' || a.status === 'EXTRACTING')
    fail('OUT_OF_ORDER', 'The invoice is not ready for review yet.');
  if (a.status !== 'DRAFT')
    return { events: [], noop: true, message: 'Already submitted.' };
  if (!verified)
    fail(
      'NOT_VERIFIED',
      'Confirm that you verified the invoice fields first.',
      422,
    );
  return { events: [ev('evt-submitted', 'SUBMITTED_FOR_APPROVAL')] };
}

export function approveInvoice(state: ScenarioState): ActionResult {
  if (state.role === 'FINANCE')
    fail(
      'SELF_APPROVAL',
      'Maker-checker: Finance cannot approve an invoice it created.',
      403,
    );
  if (state.role !== 'APPROVER')
    fail(
      'FORBIDDEN',
      'Only the Approver (An) approves invoices in this scenario.',
      403,
    );
  const a = state.invoiceA;
  if (a.status === 'AWAITING_APPROVAL')
    return { events: [ev('evt-approval-a', 'APPROVAL_GRANTED')] };
  if (
    a.status === 'ABSENT' ||
    a.status === 'EXTRACTING' ||
    a.status === 'DRAFT'
  )
    fail('OUT_OF_ORDER', 'Invoice A has not been submitted for approval.');
  return { events: [], noop: true, message: 'Already approved.' };
}

export function submitSecurityInvoice(state: ScenarioState): ActionResult {
  if (state.role !== 'FINANCE')
    fail(
      'FORBIDDEN',
      'Only Finance (Linh) submits invoices for approval.',
      403,
    );
  if (!state.invoiceX.present)
    fail('OUT_OF_ORDER', 'INV-CLOUD-043 is not in the inbox yet.');
  if (state.invoiceX.status === 'BLOCKED_UNKNOWN_RECIPIENT')
    return { events: [], noop: true, message: 'Already blocked.' };
  return { events: [ev('evt-x-blocked', 'UNKNOWN_RECIPIENT_BLOCKED')] };
}

export function pauseAgent(state: ScenarioState): ActionResult {
  if (state.role !== 'OWNER')
    fail('FORBIDDEN', 'Only the Owner (Minh) can pause the agent.', 403);
  if (state.agent.status !== 'ACTIVE')
    return {
      events: [],
      noop: true,
      message: `Agent is already ${state.agent.status.toLowerCase()}.`,
    };
  return { events: [ev('evt-agent-pause-requested', 'AGENT_PAUSE_REQUESTED')] };
}

export type DirectorAction =
  | 'RESET_DAY_D'
  | 'RELEASE_EXECUTION_WINDOW'
  | 'HOLD_PAY_UNKNOWN'
  | 'RELEASE_PAY_VERIFICATION'
  | 'LOAD_DAY_D_PLUS_ONE'
  | 'RELEASE_SURPLUS_CYCLE'
  | 'LOAD_SECURITY_INBOX'
  | 'SHOW_AGENT_OVERLAY'
  | 'SHOW_OUTCOME_OVERLAY'
  | 'HIDE_OVERLAY';

export const DIRECTOR_ACTIONS: DirectorAction[] = [
  'RESET_DAY_D',
  'RELEASE_EXECUTION_WINDOW',
  'HOLD_PAY_UNKNOWN',
  'RELEASE_PAY_VERIFICATION',
  'LOAD_DAY_D_PLUS_ONE',
  'RELEASE_SURPLUS_CYCLE',
  'LOAD_SECURITY_INBOX',
  'SHOW_AGENT_OVERLAY',
  'SHOW_OUTCOME_OVERLAY',
  'HIDE_OVERLAY',
];

/**
 * Director guards. Pure: the Director window runs the same function against the shared
 * snapshot before it sends a command, and the main window runs it again before it applies it.
 * RESET_DAY_D is handled by the store (it replaces the state), so it has no events here.
 */
export function directorAction(
  state: ScenarioState,
  action: DirectorAction,
): ActionResult {
  const a = state.invoiceA;
  switch (action) {
    case 'RESET_DAY_D':
      return { events: [] };
    case 'RELEASE_EXECUTION_WINDOW':
      if (state.director.windowReleased)
        return {
          events: [],
          noop: true,
          message: 'The execution window is already open.',
        };
      if (a.status !== 'READY_WAITING_WINDOW')
        return fail(
          'OUT_OF_ORDER',
          'Invoice A is not ready: approve it as An and wait for "Ready - waiting for approved window".',
        );
      return { events: [ev('evt-window-released', 'WINDOW_RELEASED')] };
    case 'HOLD_PAY_UNKNOWN':
      if (a.status === 'PAID')
        return fail('OUT_OF_ORDER', 'The payment is already verified.');
      if (state.director.holdPayUnknown)
        return { events: [], noop: true, message: 'The hold is already on.' };
      return {
        events: [
          ev(`evt-hold-on-${state.log.length}`, 'HOLD_SET', { flag: true }),
        ],
      };
    case 'RELEASE_PAY_VERIFICATION':
      if (a.status === 'PAID')
        return {
          events: [],
          noop: true,
          message: 'The payment is already verified.',
        };
      if (a.status !== 'OUTCOME_UNKNOWN')
        return fail(
          'OUT_OF_ORDER',
          'The payment has not reached "Outcome unknown" yet. Release the execution window and wait.',
        );
      return {
        events: [
          ev(`evt-hold-off-${state.log.length}`, 'HOLD_SET', { flag: false }),
          ev('evt-pay-verified', 'PAY_VERIFIED'),
        ],
      };
    case 'LOAD_DAY_D_PLUS_ONE':
      if (state.director.dayPlusOne)
        return { events: [], noop: true, message: 'D+1 is already loaded.' };
      if (a.status !== 'PAID' || a.recon !== 'MATCHED')
        return fail(
          'OUT_OF_ORDER',
          'Verify the payment and wait for reconciliation to be Matched before loading D+1.',
        );
      // Revenue and the approved C land together, before any surplus is computed.
      return {
        events: [
          ev('evt-day-advanced', 'DAY_ADVANCED', {
            clock: fixture.clock.nextDay,
          }),
          ev('evt-revenue-confirmed', 'REVENUE_CONFIRMED'),
          ev('evt-c-approved', 'C_APPROVED'),
        ],
      };
    case 'RELEASE_SURPLUS_CYCLE': {
      if (
        state.supply.status === 'SUBMITTED' ||
        state.supply.status === 'CONFIRMED'
      )
        return {
          events: [],
          noop: true,
          message: 'The supply cycle already ran.',
        };
      if (!state.director.dayPlusOne || !state.cApproved)
        return fail(
          'OUT_OF_ORDER',
          'Load D+1 (revenue and C approved) before the surplus cycle.',
        );
      if (state.agent.status !== 'ACTIVE')
        return fail(
          'AGENT_PAUSED',
          'The agent is not active: the cycle is skipped.',
        );
      const plan = supplyPlan(state);
      if (!plan.eligible)
        return fail(
          'NOT_ELIGIBLE',
          'The current surplus is not eligible for supply.',
        );
      return {
        events: [
          ev('evt-supply-submitted', 'SUPPLY_SUBMITTED', {
            amount: plan.amount.toString(),
          }),
        ],
      };
    }
    case 'LOAD_SECURITY_INBOX':
      if (state.director.securityLoaded)
        return {
          events: [],
          noop: true,
          message: 'The security invoice is already loaded.',
        };
      return { events: [ev('evt-security-inbox', 'SECURITY_INBOX_LOADED')] };
    case 'SHOW_AGENT_OVERLAY':
      return {
        events: [
          ev(`evt-overlay-${state.log.length}`, 'OVERLAY_SET', {
            overlay: 'AGENT',
          }),
        ],
      };
    case 'SHOW_OUTCOME_OVERLAY':
      if (state.supply.status !== 'CONFIRMED')
        return fail(
          'OUT_OF_ORDER',
          'The outcome frame is computed from S5: confirm the supply first.',
        );
      return {
        events: [
          ev(`evt-overlay-${state.log.length}`, 'OVERLAY_SET', {
            overlay: 'OUTCOME',
          }),
        ],
      };
    case 'HIDE_OVERLAY':
      return {
        events: [
          ev(`evt-overlay-${state.log.length}`, 'OVERLAY_SET', {
            overlay: 'NONE',
          }),
        ],
      };
    default:
      return fail(
        'UNKNOWN_ACTION',
        `Unknown director action ${String(action)}.`,
        404,
      );
  }
}

/** Scene 11: the four outcome lines, computed from the S5 state. */
export function outcomeLines(state: ScenarioState): string[] {
  const money = (value: bigint) =>
    formatUnits(value, 6, { minFraction: 0, maxFraction: 2 });
  const paid = state.ledger.vendorPaid;
  const matched = state.invoiceA.recon === 'MATCHED';
  const reservesKept =
    tBreakdown(state).payrollReserve +
      tBreakdown(state).upcomingBillReserve +
      T_FLOOR <=
    big(state.ledger.t);
  return [
    `Invoice A: paid ${money(big(paid))} / ${matched ? 'matched' : 'matching'}`,
    reservesKept
      ? 'Payroll and upcoming bill reserves preserved'
      : 'Reserve check failed',
    state.invoiceA.paymentCount === 1 && state.invoiceA.paySubmissions === 1
      ? 'One payment / unknown outcome verified before completion'
      : 'Payment count check failed',
    `Only ${money(big(state.supply.amount ?? '0'))} surplus supplied / agent now ${state.agent.status === 'PAUSED' ? 'paused' : state.agent.status.toLowerCase()}`,
  ];
}

export const OUTCOME_FOOTER =
  'Synthetic business scenario. Execution/evidence mode labeled throughout. No guaranteed yield.';
