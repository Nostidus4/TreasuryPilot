/**
 * Recording-only scenario for the 7m30 demo (TreasuryPilot_Demo_7m30_Runbook_VI.md,
 * fixture TP-DEMO-7M30-01). SIMULATION: no API, no signing, no broadcast.
 * Amounts are USDC base units (6 decimals) as bigint; never floats.
 */
import { useSyncExternalStore } from 'react';

import { formatUnits } from '@/lib/money';

export const U = 1_000_000n;
export const usd = (value: bigint) => formatUnits(value, 6, { minFraction: 0 });
/** Rounded to cents for estimates (formatUnits truncates). */
export const usdRounded = (value: bigint) =>
  formatUnits(((value + 5_000n) / 10_000n) * 10_000n, 6);

export const FX = {
  scenarioId: 'TP-DEMO-7M30-01',
  org: 'Northstar API',
  envLabel: 'SIMULATION / SYNTHETIC DATA',
  clock: {
    start: '2026-10-16T10:04:00Z',
    approval: '2026-10-16T10:04:15Z',
    planReady: '2026-10-16T10:04:30Z',
    window: '2026-10-16T10:05:00Z',
    planExpires: '2026-10-16T10:19:30Z',
    nextDay: '2026-10-17T10:04:00Z',
    supplyCycle: '2026-10-17T10:05:00Z',
  },
  tFloor: 100n * U,
  o1Buffer: 100n * U,
  a: {
    id: 'inv-cloud-042',
    number: 'INV-CLOUD-042',
    fileName: 'INV-CLOUD-042.pdf',
    vendor: 'Northstar Cloud Vendor',
    payeeAlias: 'VENDOR_CLOUD',
    standard: 1_000n * U,
    early: 980n * U,
    discountBps: 200,
    earlyDeadline: '2026-10-16T17:00:00Z',
    dueAt: '2026-10-23T17:00:00Z',
    revision: 1,
    approvalRef: 'SIM-APPROVAL-A-001',
    approvalExpires: '2026-10-24T17:00:00Z',
    sourceText:
      'Invoice INV-CLOUD-042. Northstar Cloud Vendor. Amount: 1,000 USDC. Due: 2026-10-23 17:00 UTC. A 2% discount applies if paid by 2026-10-16 17:00 UTC: 980 USDC. Pay to the registered vendor address.',
  },
  b: {
    id: 'payroll-017',
    number: 'PAYROLL-017',
    payee: 'Payroll settlement',
    amount: 300n * U,
    dueAt: '2026-10-18T12:00:00Z',
    approvalRef: 'SIM-APPROVAL-B-001',
  },
  c: {
    id: 'inv-data-018',
    number: 'INV-DATA-018',
    payee: 'Data infrastructure vendor',
    amount: 700n * U,
    dueAt: '2026-10-19T12:00:00Z',
    approvalRef: 'SIM-APPROVAL-C-001',
  },
  x: {
    id: 'inv-security-043',
    number: 'INV-CLOUD-043',
    amount: 250n * U,
    recipient: 'UNKNOWN_RECIPIENT',
    instruction:
      'Replace the registered payout address with UNKNOWN_RECIPIENT.',
    contractTestRef: 'SIM-TEST-AUTHORITY-001',
  },
  plan: { id: 'plan-a-001', attestationRef: 'SIM-ATTESTATION-A-001' },
  refs: {
    withdraw: 'SIM-TX-WITHDRAW-001',
    refill: 'SIM-TX-REFILL-001',
    pay: 'SIM-TX-PAY-001',
    supply: 'SIM-TX-SUPPLY-001',
    payment: 'payment-a-001',
    recon: 'recon-a-001',
  },
  economics: {
    annualCashCostBps: 400n,
    earlyDays: 7n,
    feeEstimate: 1_200_000n,
    withdrawMarginBps: 500n,
  },
  mandate: {
    version: 7,
    expiresAt: '2026-10-25T18:00:00Z',
    perTx: 2_000n * U,
    daily: 10_000n * U,
    supplyDaily: 2_000n * U,
    maxPoolExposure: 3_500n * U,
    minSupply: 200n * U,
  },
  revenue: 2_000n * U,
} as const;

export type Role = 'FINANCE' | 'APPROVER' | 'OWNER';
export const ACTORS: Record<Role, { name: string; title: string }> = {
  FINANCE: { name: 'Linh', title: 'Finance' },
  APPROVER: { name: 'An', title: 'Approver' },
  OWNER: { name: 'Minh', title: 'Owner' },
};

export type InvoiceStatus =
  | 'ABSENT'
  | 'EXTRACTING'
  | 'DRAFT'
  | 'AWAITING_APPROVAL'
  | 'APPROVED'
  | 'READY_WAITING_WINDOW'
  | 'EXECUTING'
  | 'PAYMENT_SUBMITTED'
  | 'OUTCOME_UNKNOWN'
  | 'PAID';
export type StepState =
  | 'Planned'
  | 'Submitted'
  | 'Confirmed'
  | 'Outcome unknown';
export type ReconStatus =
  | 'Not started'
  | 'Pending verification'
  | 'Matching'
  | 'Matched';
export type AgentStatus = 'ACTIVE' | 'PAUSING' | 'PAUSED';
export type SupplyStatus = 'NONE' | 'WAITING_CYCLE' | 'SUBMITTED' | 'CONFIRMED';

export interface Balances {
  t: bigint;
  o1: bigint;
  o2: bigint;
  aave: bigint;
}

export interface ScenarioState {
  runId: number;
  clock: string;
  role: Role;
  balances: Balances;
  /** Balances last confirmed by a verified event (stale during UNKNOWN). */
  verified: Balances;
  vendorPaid: bigint;
  revenue: bigint;
  a: {
    status: InvoiceStatus;
    reviewed: boolean;
    approvalRef?: string;
    preflight: boolean;
    steps: { withdraw: StepState; refill: StepState; pay: StepState };
    paySubmissions: number;
    recon: ReconStatus;
    holdAt: 'NONE' | 'T' | 'O1';
  };
  cApproved: boolean;
  dayPlusOne: boolean;
  supply: SupplyStatus;
  security: { loaded: boolean; blocked: boolean };
  agent: AgentStatus;
  cycleSkipped: boolean;
  holdUnknown: boolean;
  activity: Array<{ at: string; text: string; kind?: 'block' | 'chain' }>;
}

export type Event =
  | { type: 'SET_ROLE'; role: Role }
  | { type: 'UPLOAD_A' }
  | { type: 'EXTRACTION_DONE' }
  | { type: 'SET_REVIEWED'; value: boolean }
  | { type: 'SUBMIT_A' }
  | { type: 'APPROVE_A' }
  | { type: 'PLAN_READY' }
  | { type: 'RELEASE_EXECUTION_WINDOW' }
  | { type: 'PREFLIGHT_PASSED' }
  | { type: 'WITHDRAW_SUBMITTED' }
  | { type: 'WITHDRAW_CONFIRMED' }
  | { type: 'REFILL_SUBMITTED' }
  | { type: 'REFILL_CONFIRMED' }
  | { type: 'PAY_SUBMITTED' }
  | { type: 'PAY_ACK_TIMEOUT' }
  | { type: 'SET_HOLD_UNKNOWN'; value: boolean }
  | { type: 'RELEASE_PAY_VERIFICATION' }
  | { type: 'RECON_MATCHED' }
  | { type: 'LOAD_DAY_D_PLUS_ONE' }
  | { type: 'RELEASE_SURPLUS_CYCLE' }
  | { type: 'SUPPLY_CONFIRMED' }
  | { type: 'LOAD_SECURITY_INBOX' }
  | { type: 'SUBMIT_X' }
  | { type: 'PAUSE_REQUEST' }
  | { type: 'PAUSE_CONFIRMED' }
  | { type: 'CYCLE_SKIPPED' };

const S0: Balances = {
  t: 1_180n * U,
  o1: 100n * U,
  o2: 0n,
  aave: 2_000n * U,
};

export function initialState(runId = 1): ScenarioState {
  return {
    runId,
    clock: FX.clock.start,
    role: 'FINANCE',
    balances: S0,
    verified: S0,
    vendorPaid: 0n,
    revenue: 0n,
    a: {
      status: 'ABSENT',
      reviewed: false,
      preflight: false,
      steps: { withdraw: 'Planned', refill: 'Planned', pay: 'Planned' },
      paySubmissions: 0,
      recon: 'Not started',
      holdAt: 'NONE',
    },
    cApproved: false,
    dayPlusOne: false,
    supply: 'NONE',
    security: { loaded: false, blocked: false },
    agent: 'ACTIVE',
    cycleSkipped: false,
    holdUnknown: true,
    activity: [
      {
        at: FX.clock.start,
        text: 'Scenario reset to Day D (S0). PAYROLL-017 approved and reserved at T.',
      },
    ],
  };
}

const addSeconds = (iso: string, seconds: number) =>
  new Date(new Date(iso).getTime() + seconds * 1000)
    .toISOString()
    .replace('.000Z', 'Z');

/** Why an event is rejected, or null when its guard passes. */
export function guard(s: ScenarioState, e: Event): string | null {
  const a = s.a;
  switch (e.type) {
    case 'UPLOAD_A':
      return a.status === 'ABSENT' ? null : 'INV-CLOUD-042 already exists.';
    case 'EXTRACTION_DONE':
      return a.status === 'EXTRACTING' ? null : 'Not extracting.';
    case 'SET_REVIEWED':
      return a.status === 'DRAFT' && s.role === 'FINANCE'
        ? null
        : 'Only Finance can review a draft.';
    case 'SUBMIT_A':
      if (s.role !== 'FINANCE') return 'Only Finance can submit.';
      if (a.status !== 'DRAFT') return 'Not a draft.';
      return a.reviewed ? null : 'Verify the invoice fields first.';
    case 'APPROVE_A':
      if (s.role !== 'APPROVER')
        return 'A different authorized approver must approve.';
      return a.status === 'AWAITING_APPROVAL' ? null : 'Not awaiting approval.';
    case 'PLAN_READY':
      return a.status === 'APPROVED' ? null : 'Not approved.';
    case 'RELEASE_EXECUTION_WINDOW':
      if (s.agent !== 'ACTIVE') return 'Agent is paused.';
      return a.status === 'READY_WAITING_WINDOW'
        ? null
        : 'Plan is not waiting for its window.';
    case 'PREFLIGHT_PASSED':
      return a.status === 'EXECUTING' && !a.preflight ? null : 'No preflight.';
    case 'WITHDRAW_SUBMITTED':
      return a.preflight && a.steps.withdraw === 'Planned' ? null : 'Skip.';
    case 'WITHDRAW_CONFIRMED':
      return a.steps.withdraw === 'Submitted' ? null : 'Skip.';
    case 'REFILL_SUBMITTED':
      return a.steps.withdraw === 'Confirmed' && a.steps.refill === 'Planned'
        ? null
        : 'Skip.';
    case 'REFILL_CONFIRMED':
      return a.steps.refill === 'Submitted' ? null : 'Skip.';
    case 'PAY_SUBMITTED':
      // expectedPaymentSubmissionCount: 1, never a second payment.
      return a.steps.refill === 'Confirmed' && a.paySubmissions === 0
        ? null
        : 'Skip.';
    case 'PAY_ACK_TIMEOUT':
      return a.status === 'PAYMENT_SUBMITTED' ? null : 'Skip.';
    case 'RELEASE_PAY_VERIFICATION':
      return a.status === 'OUTCOME_UNKNOWN'
        ? null
        : 'PAY is not in Outcome unknown.';
    case 'RECON_MATCHED':
      return a.status === 'PAID' && a.recon === 'Matching' ? null : 'Skip.';
    case 'LOAD_DAY_D_PLUS_ONE':
      if (s.dayPlusOne) return 'Day D+1 is already loaded.';
      return a.recon === 'Matched' ? null : 'Finish invoice A first (Matched).';
    case 'RELEASE_SURPLUS_CYCLE':
      if (!s.dayPlusOne) return 'Load Day D+1 first.';
      if (s.agent !== 'ACTIVE') return 'Agent is paused.';
      return s.supply === 'WAITING_CYCLE' ? null : 'Supply cycle already ran.';
    case 'SUPPLY_CONFIRMED':
      return s.supply === 'SUBMITTED' ? null : 'Skip.';
    case 'LOAD_SECURITY_INBOX':
      return s.security.loaded ? 'Security inbox is already loaded.' : null;
    case 'SUBMIT_X':
      if (s.role !== 'FINANCE') return 'Only Finance can submit.';
      return s.security.loaded && !s.security.blocked ? null : 'Skip.';
    case 'PAUSE_REQUEST':
      if (s.role !== 'OWNER') return 'Only the owner can pause the agent.';
      return s.agent === 'ACTIVE' ? null : 'Agent is not active.';
    case 'PAUSE_CONFIRMED':
      return s.agent === 'PAUSING' ? null : 'Skip.';
    case 'CYCLE_SKIPPED':
      return s.agent === 'PAUSED' && !s.cycleSkipped ? null : 'Skip.';
    default:
      return null;
  }
}

/** Pure reducer. Ledger deltas follow runbook §6.2; guards make each event apply once. */
export function reduce(s: ScenarioState, e: Event): ScenarioState {
  if (guard(s, e)) return s;
  const n: ScenarioState = {
    ...s,
    a: { ...s.a, steps: { ...s.a.steps } },
    balances: { ...s.balances },
    security: { ...s.security },
    activity: [...s.activity],
  };
  const log = (text: string, kind?: 'block' | 'chain') =>
    n.activity.push({ at: n.clock, text, kind });
  const tick = (seconds: number) => (n.clock = addSeconds(n.clock, seconds));
  const b = n.balances;
  switch (e.type) {
    case 'SET_ROLE':
      n.role = e.role;
      break;
    case 'UPLOAD_A':
      n.a.status = 'EXTRACTING';
      log('Linh uploaded INV-CLOUD-042.pdf. Request inv-cloud-042 created.');
      break;
    case 'EXTRACTION_DONE':
      n.a.status = 'DRAFT';
      log('Recorded extraction returned a draft (revision 1).');
      break;
    case 'SET_REVIEWED':
      n.a.reviewed = e.value;
      break;
    case 'SUBMIT_A':
      n.a.status = 'AWAITING_APPROVAL';
      log('Linh submitted INV-CLOUD-042 for approval.');
      break;
    case 'APPROVE_A':
      n.clock = FX.clock.approval;
      n.a.status = 'APPROVED';
      n.a.approvalRef = FX.a.approvalRef;
      n.a.holdAt = 'T';
      log(
        'An approved INV-CLOUD-042 (simulated signature SIM-APPROVAL-A-001).',
      );
      break;
    case 'PLAN_READY':
      n.clock = FX.clock.planReady;
      n.a.status = 'READY_WAITING_WINDOW';
      log('Plan plan-a-001 computed: EARLY 980. Waiting for approved window.');
      break;
    case 'RELEASE_EXECUTION_WINDOW':
      n.clock = FX.clock.window;
      n.a.status = 'EXECUTING';
      log('Approved execution window opened. Agent started preflight.');
      break;
    case 'PREFLIGHT_PASSED':
      tick(2);
      n.a.preflight = true;
      log('Preflight passed: approval, payee, policy, snapshot, pool, gas.');
      break;
    case 'WITHDRAW_SUBMITTED':
      tick(3);
      n.a.steps.withdraw = 'Submitted';
      log('WITHDRAW 210 submitted (SIM-TX-WITHDRAW-001).', 'chain');
      break;
    case 'WITHDRAW_CONFIRMED':
      tick(6);
      n.a.steps.withdraw = 'Confirmed';
      b.t += 210n * U;
      b.aave -= 210n * U;
      n.verified = { ...b };
      log('WITHDRAW 210 confirmed. Read-back: T 1,390, Aave 1,790.', 'chain');
      break;
    case 'REFILL_SUBMITTED':
      tick(3);
      n.a.steps.refill = 'Submitted';
      log('REFILL 980 T → O1 submitted (SIM-TX-REFILL-001).', 'chain');
      break;
    case 'REFILL_CONFIRMED':
      tick(6);
      n.a.steps.refill = 'Confirmed';
      b.t -= FX.a.early;
      b.o1 += FX.a.early;
      n.verified = { ...b };
      n.a.holdAt = 'O1';
      log('REFILL 980 confirmed. Hold A moved to O1.', 'chain');
      break;
    case 'PAY_SUBMITTED':
      tick(3);
      n.a.status = 'PAYMENT_SUBMITTED';
      n.a.steps.pay = 'Submitted';
      n.a.paySubmissions = 1;
      n.a.recon = 'Pending verification';
      log('PAY 980 to VENDOR_CLOUD submitted (SIM-TX-PAY-001).', 'chain');
      break;
    case 'PAY_ACK_TIMEOUT':
      tick(8);
      n.a.status = 'OUTCOME_UNKNOWN';
      n.a.steps.pay = 'Outcome unknown';
      log(
        'RPC acknowledgement lost for SIM-TX-PAY-001. Outcome unknown; payment locked, no retry.',
      );
      break;
    case 'SET_HOLD_UNKNOWN':
      n.holdUnknown = e.value;
      break;
    case 'RELEASE_PAY_VERIFICATION':
      tick(20);
      n.a.status = 'PAID';
      n.a.steps.pay = 'Confirmed';
      n.a.recon = 'Matching';
      n.a.holdAt = 'NONE';
      b.o1 -= FX.a.early;
      n.verified = { ...b };
      n.vendorPaid += FX.a.early;
      log(
        'Existing transaction SIM-TX-PAY-001 verified (confirmation policy met). INV-CLOUD-042 paid. Payment count: 1.',
        'chain',
      );
      break;
    case 'RECON_MATCHED':
      tick(4);
      n.a.recon = 'Matched';
      log('Reconciliation recon-a-001 matched: recipient, asset, amount 980.');
      break;
    case 'LOAD_DAY_D_PLUS_ONE':
      // Atomic: revenue and C land in one snapshot before any surplus cycle.
      n.clock = FX.clock.nextDay;
      n.dayPlusOne = true;
      b.t += FX.revenue;
      n.verified = { ...b };
      n.revenue += FX.revenue;
      n.cApproved = true;
      n.supply = 'WAITING_CYCLE';
      log('Scenario time advanced to Day D+1.');
      log('Revenue +2,000 USDC received at T and confirmed.', 'chain');
      log(
        'INV-DATA-018 (700, due Oct 19) approved separately by An (SIM-APPROVAL-C-001). Reserved at T.',
      );
      break;
    case 'RELEASE_SURPLUS_CYCLE':
      n.clock = FX.clock.supplyCycle;
      n.supply = 'SUBMITTED';
      log(
        'Scheduled surplus cycle: checks passed. SUPPLY 1,310 submitted (SIM-TX-SUPPLY-001).',
        'chain',
      );
      break;
    case 'SUPPLY_CONFIRMED': {
      tick(8);
      const amount = surplus(s);
      b.t -= amount;
      b.aave += amount;
      n.verified = { ...b };
      n.supply = 'CONFIRMED';
      log('SUPPLY 1,310 confirmed. T 1,100, Aave 3,100.', 'chain');
      break;
    }
    case 'LOAD_SECURITY_INBOX':
      n.security.loaded = true;
      log(
        'INV-CLOUD-043 received. Flagged for review: payout instruction differs from registry.',
      );
      break;
    case 'SUBMIT_X':
      tick(5);
      n.security.blocked = true;
      log(
        'BLOCKED_UNKNOWN_RECIPIENT: INV-CLOUD-043 submission rejected. No approval, reserve, plan or payment created.',
        'block',
      );
      break;
    case 'PAUSE_REQUEST':
      tick(10);
      n.agent = 'PAUSING';
      log('Minh requested Pause agent.');
      break;
    case 'PAUSE_CONFIRMED':
      tick(4);
      n.agent = 'PAUSED';
      log('Agent paused (simulated pause result).');
      break;
    case 'CYCLE_SKIPPED':
      tick(60);
      n.cycleSkipped = true;
      log(
        'Next agent cycle skipped: AGENT_PAUSED. No new transactions.',
        'block',
      );
      break;
  }
  return n;
}

/** Engine: the next automatic event and its delay, or null to wait. */
export function nextAuto(
  s: ScenarioState,
): { event: Event; delayMs: number } | null {
  const a = s.a;
  const at = (event: Event, delayMs: number) => ({ event, delayMs });
  if (a.status === 'EXTRACTING') return at({ type: 'EXTRACTION_DONE' }, 2500);
  if (a.status === 'APPROVED') return at({ type: 'PLAN_READY' }, 1500);
  if (a.status === 'EXECUTING') {
    if (!a.preflight) return at({ type: 'PREFLIGHT_PASSED' }, 5000);
    if (a.steps.withdraw === 'Planned')
      return at({ type: 'WITHDRAW_SUBMITTED' }, 3000);
    if (a.steps.withdraw === 'Submitted')
      return at({ type: 'WITHDRAW_CONFIRMED' }, 6000);
    if (a.steps.refill === 'Planned')
      return at({ type: 'REFILL_SUBMITTED' }, 4000);
    if (a.steps.refill === 'Submitted')
      return at({ type: 'REFILL_CONFIRMED' }, 7000);
    return at({ type: 'PAY_SUBMITTED' }, 5000);
  }
  if (a.status === 'PAYMENT_SUBMITTED')
    return at({ type: 'PAY_ACK_TIMEOUT' }, 6000);
  if (a.status === 'OUTCOME_UNKNOWN' && !s.holdUnknown)
    return at({ type: 'RELEASE_PAY_VERIFICATION' }, 10000);
  if (a.recon === 'Matching') return at({ type: 'RECON_MATCHED' }, 4000);
  if (s.supply === 'SUBMITTED') return at({ type: 'SUPPLY_CONFIRMED' }, 5000);
  if (s.agent === 'PAUSING') return at({ type: 'PAUSE_CONFIRMED' }, 3500);
  if (s.agent === 'PAUSED' && !s.cycleSkipped)
    return at({ type: 'CYCLE_SKIPPED' }, 4000);
  return null;
}

// ---- Derived values (runbook §6.3); never hard-coded text. ----

export const tCapacityForA = (balances: Balances) =>
  balances.t - FX.b.amount - FX.tFloor;
export const o1NeedForA = FX.a.early + FX.o1Buffer - S0.o1;
export const fundingGap = (() => {
  const gap = o1NeedForA - tCapacityForA(S0);
  return gap > 0n ? gap : 0n;
})();
/** ceil(gap × 105%) in base units. */
export const withdrawAmount =
  (fundingGap * (10_000n + FX.economics.withdrawMarginBps) + 9_999n) / 10_000n;
export const grossDiscount = FX.a.standard - FX.a.early;
export const earlyCashCost =
  (FX.a.early * FX.economics.annualCashCostBps * FX.economics.earlyDays) /
  (10_000n * 365n);
export const earlyNetEstimate =
  grossDiscount - earlyCashCost - FX.economics.feeEstimate;

/** Protected cash at T: B, C once approved, and the floor. */
export const tProtected = (s: ScenarioState) =>
  FX.b.amount + (s.cApproved ? FX.c.amount : 0n) + FX.tFloor;

/** Hold A at T: capped by what T can give without touching other reserves. */
export function tHoldA(s: ScenarioState) {
  if (s.a.holdAt !== 'T') return 0n;
  const room = s.balances.t - tProtected(s);
  return room < FX.a.early ? room : FX.a.early;
}
export const tUncommitted = (s: ScenarioState) =>
  s.balances.t - tProtected(s) - tHoldA(s);
export const o1HoldA = (s: ScenarioState) =>
  s.a.holdAt === 'O1' ? FX.a.early : 0n;

export function surplus(s: ScenarioState) {
  const value = s.balances.t - tProtected(s) - tHoldA(s);
  return value > 0n ? value : 0n;
}

export const isApprovedOrLater = (status: InvoiceStatus) =>
  !['ABSENT', 'EXTRACTING', 'DRAFT', 'AWAITING_APPROVAL'].includes(status);

// ---- Checkpoints for re-takes (runbook §7.2): replay, never edit state. ----

function settle(s: ScenarioState): ScenarioState {
  let next = s;
  for (let auto = nextAuto(next); auto; auto = nextAuto(next)) {
    next = reduce(next, auto.event);
  }
  return next;
}

export function replay(runId: number, events: Event[]): ScenarioState {
  return events.reduce(
    (s, e) => settle(reduce(s, e)),
    settle(initialState(runId)),
  );
}

const TAKE_C: Event[] = [
  { type: 'UPLOAD_A' },
  { type: 'SET_REVIEWED', value: true },
  { type: 'SUBMIT_A' },
  { type: 'SET_ROLE', role: 'APPROVER' },
  { type: 'APPROVE_A' },
];
const TAKE_D: Event[] = [
  ...TAKE_C,
  { type: 'RELEASE_EXECUTION_WINDOW' },
  { type: 'RELEASE_PAY_VERIFICATION' },
];
const TAKE_E: Event[] = [
  ...TAKE_D,
  { type: 'LOAD_DAY_D_PLUS_ONE' },
  { type: 'RELEASE_SURPLUS_CYCLE' },
  { type: 'LOAD_SECURITY_INBOX' },
  { type: 'SET_ROLE', role: 'FINANCE' },
];

export const CHECKPOINTS = [
  { id: 'C', label: 'Take C: plan waiting window (An)', events: TAKE_C },
  { id: 'D', label: 'Take D: S3 / Matched (Day D)', events: TAKE_D },
  { id: 'E', label: 'Take E: S5 + security inbox (Linh)', events: TAKE_E },
  {
    id: 'F',
    label: 'Take F: final state (agent paused)',
    events: [
      ...TAKE_E,
      { type: 'SUBMIT_X' },
      { type: 'SET_ROLE', role: 'OWNER' },
      { type: 'PAUSE_REQUEST' },
    ] as Event[],
  },
] as const;

// ---- Store: localStorage, shared across the recording and director windows. ----

const KEY = `treasurypilot-demo:${FX.scenarioId}`;

const serialize = (s: ScenarioState) =>
  JSON.stringify(s, (_k, v: unknown) =>
    typeof v === 'bigint' ? { $big: v.toString() } : v,
  );
const deserialize = (text: string) =>
  JSON.parse(text, (_k, v: unknown) =>
    v && typeof v === 'object' && '$big' in v
      ? BigInt((v as { $big: string }).$big)
      : v,
  ) as ScenarioState;

let cache: { text: string | null; state: ScenarioState } | null = null;

export function getState(): ScenarioState {
  const text = localStorage.getItem(KEY);
  if (cache && cache.text === text) return cache.state;
  let state: ScenarioState;
  try {
    state = text ? deserialize(text) : initialState();
  } catch {
    state = initialState();
  }
  cache = { text, state };
  return state;
}

const listeners = new Set<() => void>();
function write(state: ScenarioState) {
  const text = serialize(state);
  localStorage.setItem(KEY, text);
  cache = { text, state };
  listeners.forEach((listener) => listener());
}

/** Dispatch; stale callbacks from a previous take (runId) are dropped. */
export function dispatch(event: Event, runId?: number): string | null {
  const s = getState();
  if (runId !== undefined && runId !== s.runId) return 'Stale run.';
  const reason = guard(s, event);
  if (reason) return reason;
  write(reduce(s, event));
  return null;
}

export function resetDayD() {
  write(initialState(getState().runId + 1));
}

export function loadCheckpoint(events: readonly Event[]) {
  write(replay(getState().runId + 1, [...events]));
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (e: StorageEvent) => e.key === KEY && listener();
  window.addEventListener('storage', onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener('storage', onStorage);
  };
}

export const useScenario = () => useSyncExternalStore(subscribe, getState);
