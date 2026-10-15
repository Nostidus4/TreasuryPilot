/**
 * Hand-written contract types that follow docs/API_SPEC.md.
 * Replace with the generated `schema.d.ts` types endpoint by endpoint as the
 * API publishes them (`pnpm generate:api`).
 *
 * Amounts are decimal strings in base units (ADR-014). Addresses are 0x strings.
 */

import type { components } from '@/lib/api/schema';

export type Hex = `0x${string}`;
export type Role = 'OWN' | 'APR' | 'OPR' | 'FIN' | 'GRD' | 'ADM' | 'AUD';

export interface Page<T> {
  items: T[];
  nextCursor?: string | null;
}

/* ───────────── Identity & organizations ───────────── */

export interface User {
  id: string;
  email: string;
  name: string;
}

export interface Membership {
  orgId: string;
  orgName: string;
  roles: Role[];
}

export interface LinkedWallet {
  address: Hex;
  linkedAt: string;
}

export interface Me {
  user: User;
  memberships: Membership[];
  wallets: LinkedWallet[];
}

export interface ChecklistItem {
  key: string;
  title: string;
  description: string;
  done: boolean;
  /** App-relative path of the screen that completes this step. */
  href: string;
}

export interface Org {
  id: string;
  name: string;
  legalName?: string;
  country: string;
  displayTz: string;
  soloMode: boolean;
  autoMatch: boolean;
  treasuries: Array<{ id: string; name: string }>;
}

export interface OrgDetail {
  org: Org;
  checklist: ChecklistItem[];
}

export interface Member {
  userId: string;
  name: string;
  email: string;
  roles: Role[];
  wallet?: Hex;
  status: 'Active' | 'Invited';
  joinedAt: string;
}

/* ───────────── Treasury & chain ───────────── */

export interface Asset {
  id: string;
  symbol: string;
  decimals: number;
  address: Hex;
  isTest: boolean;
}

export interface Chain {
  chainId: number;
  name: string;
  explorerUrl: string;
  safeDeploymentAvailable: boolean;
  assets: Asset[];
}

export type WalletRole = 'T' | 'O1' | 'O2' | 'GUARDIAN';

export interface TreasuryWallet {
  role: WalletRole;
  label: string;
  safeAddress: Hex;
  balance: string;
  buffer: string;
  target: string;
  threshold: number;
  owners: Hex[];
}

export type TreasuryStatus = 'Setup' | 'Active' | 'PauseRequested' | 'Paused';

export interface Treasury {
  id: string;
  name: string;
  chainId: number;
  chainName: string;
  asset: Asset;
  moduleAddress: Hex;
  status: TreasuryStatus;
  pauseReason?: string;
}

/** One row in the organization-wide treasury view; amounts are intentionally absent. */
export interface TreasurySummary {
  id: string;
  chainId: number;
  chainName: string;
  assetId: string;
  assetSymbol: string;
  assetDecimals: number | null;
  assetIsTest: boolean | null;
  status: 'Draft' | 'ModulePending' | 'Ready' | 'Paused' | 'Revoked';
  coverage: 'UNKNOWN' | 'PARTIAL' | 'COMPLETE';
  coverageDetails: string[];
  createdAt: string;
}

export interface Coverage {
  status: 'COMPLETE' | 'PARTIAL' | 'UNKNOWN';
  acknowledged: boolean;
  details: string[];
  missing: string[];
  snapshotBlock: number | null;
  executionAllowed?: boolean;
}

export interface Budget {
  action: 'PAY' | 'REFILL';
  usedToday: string;
  dailyLimit: string;
  perRequest: string;
}

export interface Position {
  safeUsdc: string;
  aUsdc: string;
  poolLiquidity: string;
  requiredReserve: {
    paymentReserve: string;
    floor: string;
    holds: string;
    total: string;
  };
  availableForSupply: string;
  supplyApyBps: number;
  lastAction: {
    kind: 'SUPPLY' | 'WITHDRAW' | 'NONE';
    amount: string;
    at: string;
    explanation: string;
    txHash?: Hex;
  };
}

export interface ActivityItem {
  id: string;
  at: string;
  actor: 'agent' | 'user' | 'chain';
  text: string;
  href?: string;
}

export interface TreasuryState {
  treasury: Treasury;
  wallets: TreasuryWallet[];
  coverage: Coverage;
  mandate: {
    version: number;
    status: MandateStatus;
    expiresAt: string;
  } | null;
  budgets: Budget[];
  staleness: { blockNumber: number; observedAt: string; stale: boolean };
  position: Position;
  queues: {
    approvals: number;
    governance: number;
    review: number;
    reconciliation: number;
  };
  activity: ActivityItem[];
  borrowProposalId?: string;
}

export type Forecast = components['schemas']['ForecastResponse'];
export type ForecastDay = components['schemas']['ForecastDay'];
export type ForecastWallet = components['schemas']['ForecastWallet'];
export type ForecastRefill = components['schemas']['ForecastRefill'];

export interface BorrowProposal {
  id: string;
  treasuryId: string;
  reason: string;
  shortfall: string;
  dueAt: string;
  withdraw: { available: string; cost: string; note: string };
  borrow: { amount: string; aprBps: number; cost7d: string; note: string };
  healthFactorBefore: number;
  healthFactorAfter: number;
  recommended: 'WITHDRAW' | 'BORROW';
  status: 'Proposed' | 'Authorized' | 'Dismissed';
}

/* ───────────── Mandate, payees, governance ───────────── */

export type MandateStatus =
  | 'Draft'
  | 'PendingActivation'
  | 'Active'
  | 'Superseded'
  | 'Expired'
  | 'Revoked'
  | 'Discrepancy';

export interface MandateAssetPolicy {
  assetId: string;
  limits: {
    PAY: { perRequest: string; daily: string };
    REFILL: { perRequest: string; daily: string };
  };
  buffers: Array<{ wallet: Hex; minimum: string; target?: string }>;
}

export interface MandateConfig {
  actions: Array<'REFILL' | 'PAY'>;
  limits: {
    PAY: { perRequest: string; daily: string };
    REFILL: { perRequest: string; daily: string };
  };
  buffers: Array<{ wallet: WalletRole; minimum: string; target: string }>;
  assetPolicies?: MandateAssetPolicy[];
  executor: Hex;
  approvers: Hex[];
  guardian: Hex;
  validFrom: string;
  expiresAt: string;
}

export interface MandateVersion {
  version: number;
  status: MandateStatus;
  config: MandateConfig;
  createdAt: string;
  activatedAt?: string;
}

export interface DiffEntry {
  field: string;
  before: string;
  after: string;
  direction: 'LOOSER' | 'STRICTER' | 'NEUTRAL';
}

export interface MandateDraft {
  draft: MandateVersion;
  summary: string[];
  diff: DiffEntry[];
}

export type PayeeStatus =
  | 'Screening'
  | 'ScreeningHit'
  | 'AwaitingVerification'
  | 'AwaitingRegistration'
  | 'Cooling'
  | 'Active'
  | 'Deactivated';

export interface Payee {
  id: string;
  treasuryId: string;
  vendorId: string;
  vendorName: string;
  label: string;
  address: Hex;
  status: PayeeStatus;
  screening: { result: 'CLEAR' | 'HIT' | 'PENDING'; checkedAt?: string };
  oobVerified: boolean;
  activeFrom?: string;
  createdAt: string;
}

export interface DecodedCall {
  to: Hex;
  toLabel: string;
  value: string;
  /** 0 = call, 1 = delegatecall. */
  operation: 0 | 1;
  method: string;
  params: Array<{ name: string; type: string; value: string }>;
  data: Hex;
}

export type GovernanceStatus =
  | 'AwaitingSignatures'
  | 'ReadyToExecute'
  | 'Executing'
  | 'Executed'
  | 'Failed'
  | 'Superseded';

export interface GovernanceTx {
  id: string;
  kind:
    | 'DEPLOY_MODULE'
    | 'CONFIGURE_MANDATE'
    | 'ADD_PAYEE'
    | 'DEACTIVATE_PAYEE'
    | 'GRANT_EXCEPTION'
    | 'RESUME'
    | 'REVOKE';
  title: string;
  summary: string;
  status: GovernanceStatus;
  treasuryId: string;
  safeAddress: Hex;
  safeLabel: string;
  nonce: number;
  threshold: number;
  owners: Array<{ address: Hex; name: string }>;
  signatures: Array<{ owner: Hex; at: string }>;
  calls: DecodedCall[];
  diff?: DiffEntry[];
  safeTxHash: Hex;
  createdAt: string;
  createdBy: string;
  txHash?: Hex;
  failureReason?: string;
  supersededBy?: string;
}

export interface TypedData {
  domain: {
    name?: string;
    version?: string;
    chainId: number;
    verifyingContract: Hex;
  };
  types: Record<string, Array<{ name: string; type: string }>>;
  primaryType: string;
  message: Record<string, string | number | boolean>;
}

export interface TxCall {
  to: Hex;
  data: Hex;
  value?: string;
  /** When set, the wallet must be on this chain or the send is rejected. */
  chainId?: number;
}

/* ───────────── Invoices & requests ───────────── */

export type RequestStatus =
  | 'Extracting'
  | 'Draft'
  | 'AwaitingApproval'
  | 'ChangesRequested'
  | 'Approved'
  | 'Scheduled'
  | 'InFlight'
  | 'Paid'
  | 'Rejected'
  | 'Cancelled';

export interface Flag {
  id: string;
  code: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  title: string;
  detail: string;
  evidence?: Array<{ label: string; value: string }>;
  duplicateOf?: {
    requestId: string;
    invoiceNumber: string;
    vendorName: string;
    amount: string;
    dueDate: string;
    status: RequestStatus;
  };
  acknowledged?: { by: string; note: string; at: string };
}

export interface PaymentTerms {
  standardDueDate: string;
  earlyPayDate?: string;
  earlyDiscountBps?: number;
  confirmed: boolean;
}

export interface PaymentOption {
  kind: 'EARLY' | 'STANDARD';
  payBy: string;
  amount: string;
  saving: string;
}

export interface ExtractedField {
  key: string;
  label: string;
  value: string;
  /** 0..1 for AI-extracted values; null for values a person typed. */
  confidence: number | null;
  source: 'AI' | 'USER';
}

export interface PaymentRequest {
  id: string;
  invoiceNumber: string;
  vendorId: string;
  vendorName: string;
  payeeAddress: Hex;
  amount: string;
  treasuryId: string;
  dueDate: string;
  status: RequestStatus;
  source: 'MANUAL' | 'UPLOAD' | 'CSV';
  description: string;
  createdBy: { id: string; name: string };
  createdAt: string;
  revision: number;
  openFlags: number;
  highFlagsUnacked: number;
}

export interface RequestDetail extends PaymentRequest {
  version: string;
  document?: { name: string; mime: string; url: string };
  fields: ExtractedField[];
  terms: PaymentTerms;
  options: PaymentOption[];
  flags: Flag[];
  injectionWarnings: string[];
  revisions: Array<{
    revision: number;
    at: string;
    by: string;
    summary: string;
  }>;
  approvals: Array<{
    approver: Hex;
    name: string;
    at: string;
    option: PaymentOption['kind'];
  }>;
  timeline: Array<{ at: string; label: string }>;
  vendorHistory: {
    paidCount: number;
    averageAmount: string;
    lastAmount: string;
    usualPayee: Hex;
    payeeChanged: boolean;
  };
  cancelOnchain: 'NOT_NEEDED' | 'REQUIRED' | 'PENDING' | 'CONFIRMED';
  planId?: string;
  /** Present when the signed-in user may not approve, with the reason. */
  approvalBlocked?: { code: 'MAKER_CHECKER'; message: string };
}

export interface RequestInput {
  vendorId: string;
  invoiceNumber: string;
  amount: string;
  dueDate: string;
  description: string;
  treasuryId: string;
  earlyPayDate?: string;
  earlyDiscountBps?: number;
}

export interface Vendor {
  id: string;
  name: string;
  payeeAddress: Hex | null;
  payeeStatus: PayeeStatus | null;
}

export interface CsvImportResult {
  created: Array<{ row: number; requestId: string; invoiceNumber: string }>;
  errors: Array<{ row: number; code: string; message: string }>;
}

/* ───────────── Planning & execution ───────────── */

export type StepStatus =
  | 'Planned'
  | 'Submitted'
  | 'Pending'
  | 'Confirmed'
  | 'Verified'
  | 'Final'
  | 'Dropped'
  | 'Replaced'
  | 'Unknown'
  | 'Failed'
  | 'Skipped';

export type PlanStatus =
  | 'Proposed'
  | 'Validated'
  | 'Executing'
  | 'Completed'
  | 'PartiallyCompleted'
  | 'Rejected'
  | 'Unknown';

export interface Plan {
  id: string;
  treasuryId: string;
  createdAt: string;
  status: PlanStatus;
  plannerSource: 'AI' | 'RULE_BASED' | 'UNKNOWN';
  expectedSaving: string | null;
  totalAmount: string | null;
  stepCount: number;
}

export interface PlanStep {
  id: string;
  index: number;
  kind: 'REFILL' | 'PAY' | 'SUPPLY' | 'WITHDRAW' | 'SWAP';
  title: string;
  from: string;
  to: string;
  amount: string | null;
  requestId?: string;
  option?: PaymentOption['kind'];
  reason: string;
  status: StepStatus;
  txHash?: Hex;
  confirmations?: number;
  verification?: 'VERIFIED' | 'MISMATCH';
  /** SWAP only: the labelled router (never a production one) and the output bound. */
  venue?: 'TEST_ROUTER';
  minOut?: string;
  updatedAt: string;
}

export interface Validation {
  code: string;
  decision: 'ALLOW' | 'DENY' | 'NEEDS_APPROVAL' | 'WARN';
  message: string;
  stepId?: string;
}

export interface PlanDetail extends Plan {
  steps: PlanStep[];
  validations: Validation[];
  aiExplanation?: { text: string; model: string; generatedAt: string };
  bindingConstraints: Array<{ label: string; value: string; detail: string }>;
  attestation?: { planHash: Hex; signer: Hex; signedAt: string };
}

export interface ReviewItem {
  id: string;
  type:
    | components['schemas']['ReviewType']
    | 'EXCEPTION'
    | 'UNKNOWN_OPERATION'
    | 'FAILED_STEP'
    | 'VERIFICATION_MISMATCH'
    | 'FEE_ACCEPTANCE';
  title: string;
  detail: string;
  status: 'Open' | 'Resolved';
  createdAt: string;
  treasuryId?: string;
  requestId?: string;
  planId?: string;
  roles: Role[];
  actions: Array<
    components['schemas']['ReviewAction'] | 'RESOLVE' | 'EDIT_REAPPROVE'
  >;
  /** Optimistic-concurrency token; echoed back when acting. */
  version: components['schemas']['ReviewActionRequest']['version'];
  /** Deadline from the routing table (recovery §8.3). */
  slaDueAt?: string;
  reasonCodes?: string[];
  completedSteps?: Array<{ label: string; at?: string }>;
  resolution?: { action: string; note: string; at: string };
}

export interface ExceptionDetail {
  exception: {
    requestId: string;
    status: 'Open' | 'GovernancePending' | 'Granted' | 'Rejected';
    governanceTxId?: string;
  };
  numbers: {
    requested: string;
    perRequestCap: string;
    overBy: string;
    dailyUsed: string;
    dailyLimit: string;
  };
  aiDraft?: ExceptionAiDraft | null;
}

export interface ExceptionAiDraft {
  source: 'AI' | 'TEMPLATE';
  draft: {
    summary: string;
    reasons: { text: string; evidence_ids: string[] }[];
    alternatives: string[];
  };
}

/* ───────────── Reconciliation, fees, metrics ───────────── */

export interface Reconciliation {
  id: string;
  requestId: string;
  invoiceNumber: string;
  vendorName: string;
  amount: string;
  paidAt: string;
  txHash: Hex;
  status: 'Unmatched' | 'Matched' | 'Discrepancy';
  evidenceComplete: boolean;
  easUid?: Hex;
  note?: string;
}

export type FeePresetId = components['schemas']['FeePreset'];

/** Wire shape of GET .../fee-policy (the schema types it as a free-form object). */
export interface FeePolicyResponse {
  active: FeePolicyRow | null;
  proposal:
    | (FeePolicyRow & {
        id: string;
        proposedAt: string;
        basis: {
          avgPlanFee7dWei: string;
          p90PlanFee7dWei: string;
          plansPerDay7d: number;
        };
      })
    | null;
  spentTodayWei: string;
  day: string;
  history: Array<
    | {
        kind: 'POLICY';
        id: string;
        at: string;
        by: string;
        preset: FeePresetId;
        maxFeeMultiplierBps: number;
        perPlanThresholdWei: string;
        dailyBudgetWei: string;
      }
    | {
        kind: 'PLAN_FEE';
        id: string;
        at: string;
        by: string;
        planId: string;
        estimatedFeeWei: string;
        acceptedCapWei: string;
      }
  >;
}

interface FeePolicyRow {
  preset: FeePresetId;
  maxFeeMultiplierBps: number;
  tipPercentile: number;
  perPlanThresholdWei: string;
  dailyBudgetWei: string;
  acceptedAt: string | null;
}

/** The review-queue fields the held-plan banner reads (type FEE_APPROVAL). */
export interface FeeReviewItem {
  id: string;
  treasuryId: string;
  planId: string | null;
  feeEstimateWei: string | null;
  slaDueAt: string;
  type: string;
  status: string;
}

export interface FeePolicy {
  proposalId: string | null;
  active: FeePolicyRow | null;
  proposal: FeePolicyRow | null;
  basis: { avgPlanFeeWei: string; p90PlanFeeWei: string; plansPerDay: number };
  spentTodayWei: string;
  history: FeePolicyResponse['history'];
}

export type OperationsMetrics = components['schemas']['OperationsMetrics'];

export interface SavingsMetrics {
  totals: { baseline: string; actual: string; saved: string };
  perRequest: Array<{
    requestId: string;
    invoiceNumber: string;
    vendorName: string;
    baseline: string;
    actual: string;
    saved: string;
  }>;
  skipped: number;
  warnings: string[];
  methodology: string;
}

/* ───────────── Notifications & Copilot ───────────── */

export interface Notification {
  id: string;
  at: string;
  kind: 'approval' | 'governance' | 'execution' | 'review' | 'system';
  title: string;
  body: string;
  href: string;
  read: boolean;
}

export interface CopilotMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations: Array<{ label: string; href: string }>;
}

/* ───────────── Live events ───────────── */

export interface ServerEvent {
  id: string;
  type: 'plan' | 'operation' | 'request' | 'notification' | 'governance';
  entityId: string;
}
