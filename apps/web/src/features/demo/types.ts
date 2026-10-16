/** Contract between the demo mock API (src/mocks/scenario) and the demo screens. */

export type DemoRole = 'FINANCE' | 'APPROVER' | 'OWNER';

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

export type ExecutionStatus =
  | 'NOT_STARTED'
  | 'PREFLIGHT'
  | 'RUNNING'
  | 'OUTCOME_UNKNOWN'
  | 'COMPLETED';

export type ReconStatus =
  | 'NONE'
  | 'PENDING_VERIFICATION'
  | 'MATCHING'
  | 'MATCHED';

export type StepState =
  | 'PLANNED'
  | 'SUBMITTED'
  | 'CONFIRMED'
  | 'OUTCOME_UNKNOWN';

export type FundingHold = 'NONE' | 'AT_T' | 'AT_O1' | 'RELEASED';

export type AgentStatus = 'ACTIVE' | 'PAUSING' | 'PAUSED';

export type SupplyStatus = 'NOT_READY' | 'READY' | 'SUBMITTED' | 'CONFIRMED';

export type Overlay = 'NONE' | 'AGENT' | 'OUTCOME';

export const STEP_IDS = [
  'step-withdraw-001',
  'step-refill-001',
  'step-pay-001',
] as const;
export type StepId = (typeof STEP_IDS)[number];

export interface Step {
  status: StepState;
  reference: string | null;
}

export interface Ledger {
  t: string;
  o1: string;
  o2: string;
  aave: string;
  vendorPaid: string;
  revenue: string;
}

export interface ActivityEntry {
  id: string;
  at: string;
  text: string;
}

export interface LogEntry {
  id: string;
  type: EventType;
  at: string;
}

export type EventType =
  | 'UPLOAD_ACCEPTED'
  | 'EXTRACTION_DONE'
  | 'SUBMITTED_FOR_APPROVAL'
  | 'APPROVAL_GRANTED'
  | 'PLAN_READY'
  | 'WINDOW_RELEASED'
  | 'PREFLIGHT_PASSED'
  | 'WITHDRAW_SUBMITTED'
  | 'WITHDRAW_CONFIRMED'
  | 'REFILL_SUBMITTED'
  | 'REFILL_CONFIRMED'
  | 'PAY_SUBMITTED'
  | 'ACK_TIMEOUT'
  | 'PAY_VERIFIED'
  | 'RECON_MATCHED'
  | 'HOLD_SET'
  | 'DAY_ADVANCED'
  | 'REVENUE_CONFIRMED'
  | 'C_APPROVED'
  | 'SUPPLY_SUBMITTED'
  | 'SUPPLY_CONFIRMED'
  | 'SECURITY_INBOX_LOADED'
  | 'UNKNOWN_RECIPIENT_BLOCKED'
  | 'AGENT_PAUSE_REQUESTED'
  | 'AGENT_PAUSED'
  | 'OVERLAY_SET';

export interface ScenarioState {
  version: 1;
  scenarioId: string;
  /** Incremented by every reset; asynchronous callbacks from an older run are dropped. */
  runId: number;
  clock: string;
  role: DemoRole;
  ledger: Ledger;
  /** C was approved on D+1: its 700 reserve sits at T. */
  cApproved: boolean;
  invoiceA: {
    status: InvoiceStatus;
    execution: ExecutionStatus;
    recon: ReconStatus;
    planReady: boolean;
    approvalReference: string | null;
    createdBy: string | null;
    approvedBy: string | null;
    revision: number;
    steps: Record<StepId, Step>;
    fundingHold: FundingHold;
    /** How many times PAY was submitted: never more than one. */
    paySubmissions: number;
    /** Payments verified and counted: never more than one. */
    paymentCount: number;
    /** Last verified balance stage; stale while the outcome is unknown. */
    lastVerifiedStage: string;
  };
  supply: {
    status: SupplyStatus;
    amount: string | null;
    reference: string | null;
  };
  invoiceX: {
    present: boolean;
    status: 'NONE' | 'FLAGGED_REVIEW' | 'BLOCKED_UNKNOWN_RECIPIENT';
    approvals: number;
    reserves: number;
    plans: number;
    payments: number;
  };
  agent: { status: AgentStatus };
  activity: ActivityEntry[];
  director: {
    /** Hold PAY at Outcome unknown until released (default on). */
    holdPayUnknown: boolean;
    windowReleased: boolean;
    dayPlusOne: boolean;
    securityLoaded: boolean;
    overlay: Overlay;
  };
  applied: string[];
  log: LogEntry[];
}

export interface FixtureInvoiceA {
  id: string;
  number: string;
  payeeId: string;
  payingWallet: string;
  standardAmount: string;
  earlyAmount: string;
  discountBps: number;
  earlyDeadline: string;
  dueAt: string;
  createdBy: string;
  approvedBy: string;
  revision: number;
  approvalReference: string;
  approvalExpiresAt: string;
}

export interface FixtureObligation {
  id: string;
  number: string;
  payeeId: string;
  payingWallet: string;
  amount: string;
  dueAt: string;
  executionWindowOpensAt: string;
  reserveLocation: string;
  approvalReference: string;
}

export interface FixtureAccount {
  id: string;
  name: string;
  initialBalance: string;
  buffer: string;
  target: string;
}

export interface FixtureLedgerRow {
  id: string;
  label: string;
  t: string;
  o1: string;
  o2: string;
  aave: string;
  cumulativeVendorPaid: string;
  cumulativeRevenue: string;
  total: string;
}

export interface DemoFixture {
  scenarioId: string;
  organization: { id: string; name: string; businessType: string };
  environment: { label: string };
  clock: {
    start: string;
    invoiceApprovalAt: string;
    planReadyAt: string;
    executionWindowOpensAt: string;
    planExpiresAt: string;
    nextDay: string;
    nextDaySupplyCycleOpensAt: string;
  };
  actors: Array<{ id: string; name: string; role: string }>;
  accounts: [FixtureAccount, FixtureAccount, FixtureAccount];
  payees: Array<{
    id: string;
    name: string;
    addressAlias: string;
    status: string;
  }>;
  pool: {
    id: string;
    name: string;
    initialSupplied: string;
    availableToWithdraw: string;
    enabled: boolean;
    hasTreasuryDebt: boolean;
    healthCheck: string;
  };
  mandate: {
    id: string;
    version: number;
    status: string;
    expiresAt: string;
    allowedActions: string[];
    payPerTx: string;
    payDaily: string;
    refillPerTx: string;
    refillDaily: string;
    withdrawPerTx: string;
    withdrawDaily: string;
    supplyPerTx: string;
    supplyDaily: string;
    maxPoolExposure: string;
    reserveHorizonDays: number;
    withdrawMarginBps: number;
    minSupplyAmount: string;
    borrowRequiresSeparateOwnerGrant: boolean;
    unknownRecipientPolicy: string;
    refillPaths: Array<{ from: string; to: string }>;
  };
  documents: Array<{
    id: string;
    fileName: string;
    invoiceId: string;
    sourceText: string;
    extractionSource: string;
  }>;
  invoices: [FixtureInvoiceA, FixtureObligation, FixtureObligation];
  economics: {
    source: string;
    annualCashCostBps: number;
    earlyPaymentDays: number;
    earlyPaymentFeeEstimateInUsdc: string;
    minimumEarlyNetBenefit: string;
    supplyFeeRiskEconomicCheck: string;
    note: string;
  };
  paymentPlan: {
    id: string;
    selectedTerm: string;
    source: string;
    approvalReference: string;
    attestationReference: string;
    steps: Array<{
      id: string;
      action: string;
      from: string;
      to: string;
      amount: string;
    }>;
  };
  mockEvidence: {
    withdrawReference: string;
    refillReference: string;
    payReference: string;
    supplyReference: string;
    paymentId: string;
    reconciliationId: string;
  };
  ledger: FixtureLedgerRow[];
  securityScenario: {
    invoiceId: string;
    number: string;
    amount: string;
    recipientAlias: string;
    expectedOnSubmit: string;
    contractTestReference: string;
    instruction: string;
  };
}

/** One check of the supply plan. */
export interface SupplyCheckView {
  id: string;
  label: string;
  pass: boolean;
}

/** `GET /v1/demo/scenario`. Amounts are base-unit decimal strings. */
export interface ScenarioView {
  state: ScenarioState;
  stage: string | null;
  follower: boolean;
  t: {
    balance: string;
    payrollReserve: string;
    floor: string;
    upcomingBillReserve: string;
    fundingHoldA: string;
    free: string;
  };
  o1: {
    balance: string;
    buffer: string;
    executionHold: string;
    spendable: string;
  };
  cash: string;
  aave: string;
  total: string;
  funding: {
    o1Need: string;
    tCapacity: string;
    gap: string;
    marginBps: number;
    withdraw: string;
  };
  economics: {
    standard: string;
    early: string;
    discount: string;
    cashCost: string;
    feeAllowance: string;
    net: string;
  };
  allocation: {
    tBalance: string;
    payroll: string;
    upcomingBill: string;
    floor: string;
    protectedTotal: string;
    surplus: string;
  };
  supplyPlan: {
    amount: string;
    exposureAfter: string;
    exposureCap: string;
    checks: SupplyCheckView[];
    eligible: boolean;
  };
  outcome: { lines: string[]; footer: string };
  fixture: DemoFixture;
}
