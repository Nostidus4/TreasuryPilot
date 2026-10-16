/**
 * In-memory backend used while the real API is not available.
 * It follows docs/API_SPEC.md and keeps one coherent demo story.
 * State resets on reload; only the session flag survives in sessionStorage.
 */
import { keccak256, toHex } from 'viem';

import type {
  ActivityItem,
  BorrowProposal,
  Chain,
  CopilotMessage,
  DecodedCall,
  DiffEntry,
  ExceptionWire,
  FeePolicyResponse,
  FeeReviewItem,
  Flag,
  GovernanceTxView,
  Hex,
  MandateConfig,
  MandateVersion,
  Member,
  Notification,
  Org,
  Payee,
  PlanDetail,
  PlanStep,
  Reconciliation,
  RequestDetail,
  ReviewItem,
  Role,
  ServerEvent,
  StepStatus,
  TreasuryState,
  TreasuryWallet,
  TypedData,
  User,
  Vendor,
} from '@/lib/api/types';

/** The mock always knows everything the dashboard wants, including what the API lacks (TRS-009). */
export type MockTreasuryState = Required<
  Omit<TreasuryState, 'borrowProposalId' | 'mandate' | 'wallets'>
> &
  Pick<TreasuryState, 'borrowProposalId' | 'mandate'> & {
    wallets: Array<Required<Omit<TreasuryWallet, 'id'>>>;
  };

import { APPROVER, SEEDED_PAYMENT_INVOICE, SEEDED_PLAN_ID } from './seeded';

export const usdc = (whole: number, cents = 0) =>
  (BigInt(whole) * 1_000_000n + BigInt(cents) * 10_000n).toString();

const now = () => Date.now();
export const iso = (offsetMs = 0) => new Date(now() + offsetMs).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;
export const DAY = 24 * HOUR;
const dayIso = (days: number) => {
  const date = new Date(now() + days * DAY);
  date.setUTCHours(23, 59, 59, 0);
  return date.toISOString();
};

export const h32 = (seed: string): Hex => keccak256(toHex(seed));
const addr = (seed: string): Hex => `0x${h32(seed).slice(2, 42)}`;

export const ADDR = {
  me: '0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266',
  an: '0x70997970C51812dc3A010C7d01b50e0d17dc79C8',
  quynh: '0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC',
  executor: '0x90F79bf6EB2c4f870365E785982E1f101E93b906',
  guardian: '0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65',
  safeT: addr('safe-t'),
  safeO1: addr('safe-o1'),
  safeO2: addr('safe-o2'),
  module: addr('module'),
  usdc: '0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238',
} satisfies Record<string, Hex>;

export const CHAINS: Chain[] = [
  {
    chainId: 11155111,
    name: 'Sepolia',
    explorerUrl: 'https://sepolia.etherscan.io',
    safeDeploymentAvailable: false,
    assets: [
      {
        id: 'usdc-sepolia',
        symbol: 'USDC',
        decimals: 6,
        address: ADDR.usdc,
        isTest: true,
      },
    ],
  },
];
const ASSET = CHAINS[0].assets[0];

const ME: User = {
  id: 'usr_linh',
  email: 'linh@northwind.test',
  name: 'Linh Tran',
};
const MINH = { id: 'usr_minh', name: 'Minh Pham' };

const OWNERS = [
  { address: ADDR.me, name: 'Linh Tran' },
  { address: ADDR.an, name: 'An Nguyen' },
  { address: ADDR.quynh, name: 'Quynh Le' },
];

interface Job {
  at: number;
  run: () => void;
}

export interface Db {
  /** 1 = demo pace; 0 = every scheduled transition happens on the next read. */
  timeScale: number;
  session: User | null;
  linkedWallets: Array<{ address: Hex; linkedAt: string }>;
  orgs: Org[];
  members: Member[];
  /** Members and creator of orgs created during the session. */
  orgMembers: Record<string, Member[]>;
  moduleEnabled: Record<string, string[]>;
  treasuries: Record<string, MockTreasuryState>;
  mandates: Record<string, MandateVersion[]>;
  payees: Payee[];
  vendors: Vendor[];
  governance: Array<
    GovernanceTxView & { effect?: () => void; signaturesHex: Hex[] }
  >;
  requests: RequestDetail[];
  plans: PlanDetail[];
  reviewItems: MockReviewItem[];
  exceptions: Record<string, ExceptionWire>;
  reconciliations: Reconciliation[];
  feePolicy: FeePolicyResponse;
  /** Real-shape FEE_APPROVAL review items; the review-items mock returns these for that type. */
  feeReviews: FeeReviewItem[];
  borrowProposals: BorrowProposal[];
  notifications: Notification[];
  copilot: Record<string, CopilotMessage[]>;
  jobs: Job[];
  listeners: Set<(event: ServerEvent) => void>;
  eventSeq: number;
}

const sessionKey = 'treasurypilot.mock-session';

/** A drawn stand-in for the stored invoice file, so the viewer has something real to show. */
function invoiceImage(
  vendor: string,
  invoiceNumber: string,
  amount: string,
  dueIso: string,
) {
  const value = (Number(BigInt(amount) / 10_000n) / 100).toLocaleString(
    'en-US',
    { minimumFractionDigits: 2 },
  );
  const escape = (text: string) =>
    text.replace(/&/g, '&amp;').replace(/</g, '&lt;');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 780" font-family="Helvetica, Arial, sans-serif">
<rect width="600" height="780" fill="#ffffff"/>
<text x="48" y="80" font-size="22" font-weight="700" fill="#18181b">${escape(vendor)}</text>
<text x="552" y="80" font-size="26" font-weight="700" fill="#18181b" text-anchor="end">INVOICE</text>
<text x="552" y="106" font-size="14" fill="#52525b" text-anchor="end">${escape(invoiceNumber)}</text>
<line x1="48" y1="140" x2="552" y2="140" stroke="#d4d4d8"/>
<text x="48" y="180" font-size="13" fill="#71717a">Bill to</text>
<text x="48" y="202" font-size="15" fill="#18181b">Northwind Labs Pte. Ltd.</text>
<text x="360" y="180" font-size="13" fill="#71717a">Due date</text>
<text x="360" y="202" font-size="15" fill="#18181b">${dueIso.slice(0, 10)}</text>
<rect x="48" y="260" width="504" height="34" fill="#f4f4f5"/>
<text x="60" y="282" font-size="13" fill="#52525b">Description</text>
<text x="540" y="282" font-size="13" fill="#52525b" text-anchor="end">Amount (USDC)</text>
<text x="60" y="326" font-size="15" fill="#18181b">Services for the period</text>
<text x="540" y="326" font-size="15" fill="#18181b" text-anchor="end">${value}</text>
<line x1="48" y1="350" x2="552" y2="350" stroke="#e4e4e7"/>
<text x="540" y="384" font-size="13" fill="#71717a" text-anchor="end">Amount due</text>
<text x="540" y="412" font-size="20" font-weight="700" fill="#18181b" text-anchor="end">${value} USDC</text>
<text x="48" y="720" font-size="12" fill="#71717a">Demo document generated by the mock API. Sepolia test asset.</text>
</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function request(
  partial: Partial<RequestDetail> &
    Pick<
      RequestDetail,
      'id' | 'invoiceNumber' | 'vendorId' | 'vendorName' | 'amount' | 'status'
    > & { due: number },
): RequestDetail {
  const { due, ...rest } = partial;
  const payee = addr(`payee-${partial.vendorId}`);
  const flags = partial.flags ?? [];
  const terms = partial.terms ?? {
    standardDueDate: dayIso(due),
    confirmed: true,
  };
  const early =
    terms.earlyPayDate && terms.earlyDiscountBps
      ? (BigInt(partial.amount) * BigInt(terms.earlyDiscountBps)) / 10000n
      : 0n;
  return {
    payeeAddress: payee,
    treasuryId: 'trs_main',
    dueDate: dayIso(due),
    source: 'UPLOAD',
    description: 'Monthly services',
    createdBy: MINH,
    createdAt: iso(-2 * DAY),
    revision: 1,
    version: 'v1',
    document: {
      name: `${partial.invoiceNumber}.svg`,
      mime: 'image/svg+xml',
      url: invoiceImage(
        partial.vendorName,
        partial.invoiceNumber,
        partial.amount,
        dayIso(due),
      ),
    },
    fields: [
      {
        key: 'vendor',
        label: 'Vendor',
        value: partial.vendorName,
        confidence: 0.99,
        source: 'AI',
      },
      {
        key: 'invoiceNumber',
        label: 'Invoice number',
        value: partial.invoiceNumber,
        confidence: 0.98,
        source: 'AI',
      },
      {
        key: 'amount',
        label: 'Amount',
        value: partial.amount,
        confidence: 0.97,
        source: 'AI',
      },
      {
        key: 'dueDate',
        label: 'Due date',
        value: dayIso(due),
        confidence: 0.94,
        source: 'AI',
      },
    ],
    terms,
    options: [
      ...(early > 0n
        ? [
            {
              kind: 'EARLY' as const,
              payBy: terms.earlyPayDate!,
              amount: (BigInt(partial.amount) - early).toString(),
              saving: early.toString(),
            },
          ]
        : []),
      {
        kind: 'STANDARD' as const,
        payBy: dayIso(due),
        amount: partial.amount,
        saving: '0',
      },
    ],
    injectionWarnings: [],
    revisions: [
      {
        revision: 1,
        at: iso(-2 * DAY),
        by: MINH.name,
        summary: 'Created from uploaded invoice',
      },
    ],
    approvals: [],
    timeline: [{ at: iso(-2 * DAY), label: 'Request created' }],
    vendorHistory: {
      paidCount: 6,
      averageAmount: partial.amount,
      lastAmount: partial.amount,
      usualPayee: payee,
      payeeChanged: false,
    },
    cancelOnchain: 'NOT_NEEDED',
    ...rest,
    flags,
    openFlags: flags.filter((flag) => !flag.acknowledged).length,
    highFlagsUnacked: flags.filter(
      (flag) => flag.severity === 'HIGH' && !flag.acknowledged,
    ).length,
  };
}

function step(
  index: number,
  partial: Pick<
    PlanStep,
    'kind' | 'title' | 'from' | 'to' | 'amount' | 'reason'
  > &
    Partial<PlanStep>,
  planId: string,
): PlanStep {
  return {
    id: `${planId}_s${index}`,
    index,
    status: 'Planned',
    updatedAt: iso(-HOUR),
    ...partial,
  };
}

const call = (
  method: string,
  params: DecodedCall['params'],
  overrides: Partial<DecodedCall> = {},
): DecodedCall => ({
  to: ADDR.module,
  toLabel: 'TreasuryPilot module',
  value: '0',
  operation: 0,
  method,
  params,
  data: `0x${h32(method + JSON.stringify(params)).slice(2, 10)}${h32(JSON.stringify(params)).slice(2)}`,
  ...overrides,
});

function baseMandate(): MandateConfig {
  return {
    actions: ['REFILL', 'PAY'],
    refillPaths: [
      { from: ADDR.safeT, to: ADDR.safeO1 },
      { from: ADDR.safeT, to: ADDR.safeO2 },
    ],
    limits: {
      PAY: { perRequest: usdc(2000), daily: usdc(10000) },
      REFILL: { perRequest: usdc(2500), daily: usdc(12000) },
    },
    // Keyed by Safe address like the API; Safe T has a minimum and no target.
    buffers: [
      { wallet: ADDR.safeT, minimum: usdc(3000) },
      { wallet: ADDR.safeO1, minimum: usdc(2000), target: usdc(6000) },
      { wallet: ADDR.safeO2, minimum: usdc(500), target: usdc(1500) },
    ],
    gasFundingCapWei: '50000000000000000',
    executor: ADDR.executor,
    approvers: [ADDR.me, ADDR.an],
    guardian: ADDR.guardian,
    validFrom: iso(-20 * DAY),
    expiresAt: iso(25 * DAY),
  };
}

export const oobPending = {
  oobMethod: null,
  oobNote: null,
  oobVerifiedBy: null,
  oobVerifiedAt: null,
};

const oobDone = (at: string) => ({
  oobMethod: 'PHONE',
  oobNote: 'Called the contact on file',
  oobVerifiedBy: 'usr_linh',
  oobVerifiedAt: at,
});

export const clearScreening = (
  checkedAt: string,
): NonNullable<Payee['screening']> => ({
  result: 'CLEAR',
  provider: 'mock',
  sourceRef: null,
  checkedAt,
  ttlUntil: new Date(Date.parse(checkedAt) + 7 * DAY).toISOString(),
});

export const vendorName = (vendorId: string) =>
  db.vendors.find((item) => item.id === vendorId)?.name ?? 'Vendor';

export function seed(): Db {
  const vendors: Vendor[] = [
    ['vnd_acurast', 'Acurast Cloud'],
    ['vnd_northstar', 'Northstar Analytics'],
    ['vnd_meridian', 'Meridian Security'],
    ['vnd_helix', 'Helix Hosting'],
    ['vnd_lumen', 'Lumen Legal'],
    ['vnd_brightpath', 'Brightpath Design'],
    ['vnd_orbit', 'Orbit Telecom'],
  ].map(([id, name]) => ({
    id,
    name,
    payeeId: `pay_${id.slice(4)}`,
    payeeAddress: addr(`payee-${id}`),
    payeeStatus: 'Active',
  }));
  vendors.push({
    id: 'vnd_quanta',
    name: 'Quanta Freight',
    payeeId: null,
    payeeAddress: null,
    payeeStatus: null,
  });

  const payees: Payee[] = vendors
    .filter((vendor) => vendor.payeeAddress)
    .map((vendor, index) => ({
      id: `pay_${vendor.id.slice(4)}`,
      vendorId: vendor.id,
      treasuryId: 'trs_main',
      label: 'Main receiving wallet',
      address: vendor.payeeAddress!,
      status: 'Active',
      screening: clearScreening(iso(-(30 - index) * DAY)),
      ...oobDone(iso(-(30 - index) * DAY)),
      registrationTxId: null,
      activeFrom: iso(-(29 - index) * DAY),
      createdAt: iso(-(30 - index) * DAY),
    }));
  payees.push({
    id: 'pay_northstar_new',
    vendorId: 'vnd_northstar',
    treasuryId: 'trs_main',
    label: 'New wallet from invoice NSA-2026-288',
    address: addr('payee-northstar-new'),
    status: 'AwaitingOwner',
    screening: clearScreening(iso(-3 * HOUR)),
    ...oobPending,
    registrationTxId: null,
    activeFrom: null,
    createdAt: iso(-3 * HOUR),
  });

  const helixPaid = request({
    id: 'req_070',
    invoiceNumber: 'HX-2026-070',
    vendorId: 'vnd_helix',
    vendorName: 'Helix Hosting',
    amount: usdc(2400),
    status: 'Paid',
    due: -6,
    createdAt: iso(-12 * DAY),
    planId: 'pln_0419',
  });

  const requests: RequestDetail[] = [
    request({
      id: 'req_104',
      invoiceNumber: 'AC-2026-104',
      vendorId: 'vnd_acurast',
      vendorName: 'Acurast Cloud',
      amount: usdc(1450),
      status: 'AwaitingApproval',
      due: 9,
      description: 'Compute and storage, September',
      terms: {
        standardDueDate: dayIso(9),
        earlyPayDate: dayIso(2),
        earlyDiscountBps: 200,
        confirmed: true,
      },
    }),
    request({
      id: 'req_288',
      invoiceNumber: 'NSA-2026-288',
      vendorId: 'vnd_northstar',
      vendorName: 'Northstar Analytics',
      amount: usdc(875),
      status: 'AwaitingApproval',
      due: 3,
      description: 'Analytics platform, Q4 seat expansion',
      payeeAddress: addr('payee-northstar-new'),
      vendorHistory: {
        paidCount: 4,
        averageAmount: usdc(520),
        lastAmount: usdc(540),
        usualPayee: addr('payee-vnd_northstar'),
        payeeChanged: true,
      },
      flags: [
        {
          id: 'flg_288_payee',
          code: 'PAYEE_ADDRESS_CHANGED',
          severity: 'HIGH',
          title: 'Payment address differs from this vendor’s registered payee',
          detail:
            'The invoice names a wallet that is not the active payee for Northstar Analytics. A changed address is the most common sign of invoice fraud.',
          evidence: [
            { label: 'Registered payee', value: addr('payee-vnd_northstar') },
            { label: 'Address on invoice', value: addr('payee-northstar-new') },
            { label: 'New payee status', value: 'Needs out-of-band check' },
          ],
        },
        {
          id: 'flg_288_amount',
          code: 'AMOUNT_ABOVE_VENDOR_AVERAGE',
          severity: 'MEDIUM',
          title: 'Amount is 68% above this vendor’s average',
          detail: 'The last four invoices averaged 520.00 USDC.',
        },
      ],
    }),
    request({
      id: 'req_033',
      invoiceNumber: 'MS-2026-033',
      vendorId: 'vnd_meridian',
      vendorName: 'Meridian Security',
      amount: usdc(1990),
      status: 'AwaitingApproval',
      due: 5,
      description: 'Penetration test, milestone 2',
      source: 'MANUAL',
      createdBy: { id: ME.id, name: ME.name },
      document: undefined,
      fields: [],
      approvalBlocked: {
        code: 'MAKER_CHECKER',
        message:
          'You created this request. Another approver must sign it (maker-checker).',
      },
    }),
    request({
      id: 'req_071',
      invoiceNumber: 'HX-2026-071',
      vendorId: 'vnd_helix',
      vendorName: 'Helix Hosting',
      amount: usdc(2400),
      status: 'AwaitingApproval',
      due: 7,
      description: 'Dedicated hosting, October',
      flags: [
        {
          id: 'flg_071_dup',
          code: 'POSSIBLE_DUPLICATE',
          severity: 'HIGH',
          title: 'Possible duplicate of a paid invoice',
          detail:
            'Same vendor and amount as HX-2026-070, which was paid 6 days ago. The invoice numbers differ by one digit.',
          duplicateOf: {
            requestId: helixPaid.id,
            invoiceNumber: helixPaid.invoiceNumber,
            vendorName: helixPaid.vendorName,
            amount: helixPaid.amount,
            dueDate: helixPaid.dueDate ?? '',
            status: 'Paid',
          },
        },
      ],
    }),
    request({
      id: 'req_512',
      invoiceNumber: 'LL-2026-512',
      vendorId: 'vnd_lumen',
      vendorName: 'Lumen Legal',
      amount: usdc(3200),
      status: 'Approved',
      due: 4,
      description: 'Contract review retainer',
      approvals: [
        {
          approver: ADDR.an,
          name: 'An Nguyen',
          at: iso(-5 * HOUR),
          option: 'STANDARD',
        },
      ],
    }),
    request({
      id: 'req_219',
      invoiceNumber: SEEDED_PAYMENT_INVOICE,
      vendorId: 'vnd_brightpath',
      vendorName: 'Brightpath Design',
      amount: usdc(640),
      status: 'Scheduled',
      due: 1,
      description: 'Brand refresh, final invoice',
      planId: 'pln_0421',
      approvals: [
        {
          approver: ADDR.an,
          name: 'An Nguyen',
          at: iso(-20 * HOUR),
          option: 'STANDARD',
        },
      ],
    }),
    request({
      id: 'req_220',
      invoiceNumber: 'OT-2026-220',
      vendorId: 'vnd_orbit',
      vendorName: 'Orbit Telecom',
      amount: usdc(310),
      status: 'Scheduled',
      due: 12,
      description: 'Connectivity, October',
      planId: 'pln_0421',
      terms: {
        standardDueDate: dayIso(12),
        earlyPayDate: dayIso(1),
        earlyDiscountBps: 200,
        confirmed: true,
      },
      approvals: [
        {
          approver: ADDR.an,
          name: 'An Nguyen',
          at: iso(-18 * HOUR),
          option: 'EARLY',
        },
      ],
    }),
    request({
      id: 'req_090',
      invoiceNumber: 'AC-2026-109',
      vendorId: 'vnd_acurast',
      vendorName: 'Acurast Cloud',
      amount: usdc(220),
      status: 'Draft',
      due: 14,
      source: 'MANUAL',
      description: 'Support add-on',
      createdBy: { id: ME.id, name: ME.name },
      document: undefined,
      fields: [],
    }),
    helixPaid,
    request({
      id: 'req_055',
      invoiceNumber: 'MS-2026-029',
      vendorId: 'vnd_meridian',
      vendorName: 'Meridian Security',
      amount: usdc(1200),
      status: 'Paid',
      due: -9,
      createdAt: iso(-15 * DAY),
      planId: 'pln_0420',
    }),
    request({
      id: 'req_056',
      invoiceNumber: 'OT-2026-198',
      vendorId: 'vnd_orbit',
      vendorName: 'Orbit Telecom',
      amount: usdc(305),
      status: 'Paid',
      due: -8,
      createdAt: iso(-14 * DAY),
      planId: 'pln_0420',
    }),
    request({
      id: 'req_044',
      invoiceNumber: 'BP-2026-201',
      vendorId: 'vnd_brightpath',
      vendorName: 'Brightpath Design',
      amount: usdc(980),
      status: 'Rejected',
      due: -2,
      createdAt: iso(-10 * DAY),
    }),
  ];

  const plans: PlanDetail[] = [
    {
      id: SEEDED_PLAN_ID,
      treasuryId: 'trs_main',
      createdAt: iso(-12 * MIN),
      status: 'Validated',
      plannerSource: 'AI',
      expectedSaving: usdc(6, 20),
      totalAmount: usdc(943, 80),
      stepCount: 3,
      steps: [
        step(
          1,
          {
            kind: 'REFILL',
            title: 'Refill Payments Safe',
            from: 'Treasury Safe (T)',
            to: 'Payments Safe (O1)',
            amount: usdc(1100),
            reason:
              'After both payments O1 would hold 3,876.20, below its 6,000.00 target. Refill is bound to request BP-2026-219.',
          },
          'pln_0421',
        ),
        step(
          2,
          {
            kind: 'PAY',
            title: 'Pay Brightpath Design',
            from: 'Payments Safe (O1)',
            to: 'Brightpath Design',
            amount: usdc(640),
            requestId: 'req_219',
            option: 'STANDARD',
            reason: 'Due tomorrow. No early-payment discount on this invoice.',
          },
          'pln_0421',
        ),
        step(
          3,
          {
            kind: 'PAY',
            title: 'Pay Orbit Telecom early',
            from: 'Payments Safe (O1)',
            to: 'Orbit Telecom',
            amount: usdc(303, 80),
            requestId: 'req_220',
            option: 'EARLY',
            reason:
              '2% discount if paid by tomorrow: saves 6.20 USDC against paying on the due date.',
          },
          'pln_0421',
        ),
      ],
      validations: [
        {
          code: 'APPROVAL_VALID',
          decision: 'ALLOW',
          message:
            'Both requests carry a valid approver signature for the current revision.',
        },
        {
          code: 'PAYEE_ACTIVE',
          decision: 'ALLOW',
          message: 'Both payees are registered and past their cooling period.',
        },
        {
          code: 'WITHIN_PER_REQUEST_LIMIT',
          decision: 'ALLOW',
          message:
            'Largest payment 640.00 is under the 2,000.00 per-request limit.',
        },
        {
          code: 'WITHIN_DAILY_LIMIT',
          decision: 'ALLOW',
          message: 'Today’s PAY total would be 3,543.80 of 10,000.00.',
        },
        {
          code: 'BUFFER_PRESERVED',
          decision: 'ALLOW',
          message:
            'O1 stays above its 2,000.00 minimum buffer after every step.',
        },
        {
          code: 'TARGET_NOT_REACHED',
          decision: 'WARN',
          message:
            'O1 ends at 4,976.20, below its 6,000.00 target. Warnings never change the decision.',
        },
      ],
      aiExplanation: {
        text: 'I scheduled Orbit Telecom early because its 2% discount expires tomorrow and the treasury has room: paying now costs 303.80 instead of 310.00. Brightpath is due tomorrow with no discount, so it goes at its standard amount. I refill O1 first so both payments leave the minimum buffer intact.',
        model: 'planner-v1',
        generatedAt: iso(-12 * MIN),
      },
      bindingConstraints: [
        {
          label: 'O1 minimum buffer',
          value: '2,000.00 USDC',
          detail: 'Caps how much can leave O1 before a refill.',
        },
        {
          label: 'REFILL per-request limit',
          value: '2,500.00 USDC',
          detail: 'Refill of 1,100.00 uses 44% of the limit.',
        },
        {
          label: 'Early-pay deadline',
          value: 'Tomorrow 23:59 UTC',
          detail: 'After this, Orbit Telecom is paid at 310.00.',
        },
      ],
      attestation: {
        planHash: h32('pln_0421'),
        signer: addr('policy-key'),
        signedAt: iso(-11 * MIN),
      },
    },
    {
      id: 'pln_0420',
      treasuryId: 'trs_main',
      createdAt: iso(-8 * DAY),
      status: 'Completed',
      plannerSource: 'RULE_BASED',
      expectedSaving: '0',
      totalAmount: usdc(1505),
      stepCount: 2,
      steps: [
        step(
          1,
          {
            kind: 'PAY',
            title: 'Pay Meridian Security',
            from: 'Payments Safe (O1)',
            to: 'Meridian Security',
            amount: usdc(1200),
            requestId: 'req_055',
            option: 'STANDARD',
            reason: 'Earliest deadline first.',
            status: 'Final',
            confirmations: 64,
            verification: 'VERIFIED',
            txHash: h32('tx-055'),
            updatedAt: iso(-8 * DAY),
          },
          'pln_0420',
        ),
        step(
          2,
          {
            kind: 'PAY',
            title: 'Pay Orbit Telecom',
            from: 'Payments Safe (O1)',
            to: 'Orbit Telecom',
            amount: usdc(305),
            requestId: 'req_056',
            option: 'STANDARD',
            reason: 'Earliest deadline first.',
            status: 'Final',
            confirmations: 64,
            verification: 'VERIFIED',
            txHash: h32('tx-056'),
            updatedAt: iso(-8 * DAY),
          },
          'pln_0420',
        ),
      ],
      validations: [
        {
          code: 'AI_UNAVAILABLE',
          decision: 'WARN',
          message:
            'The AI planner timed out. The rule-based scheduler (earliest deadline first) produced this plan.',
        },
        {
          code: 'WITHIN_DAILY_LIMIT',
          decision: 'ALLOW',
          message: 'PAY total 1,505.00 of 10,000.00.',
        },
      ],
      bindingConstraints: [],
      attestation: {
        planHash: h32('pln_0420'),
        signer: addr('policy-key'),
        signedAt: iso(-8 * DAY),
      },
    },
    {
      id: 'pln_0419',
      treasuryId: 'trs_main',
      createdAt: iso(-6 * DAY),
      status: 'PartiallyCompleted',
      plannerSource: 'AI',
      expectedSaving: '0',
      totalAmount: usdc(2890),
      stepCount: 2,
      steps: [
        step(
          1,
          {
            kind: 'PAY',
            title: 'Pay Helix Hosting',
            from: 'Payments Safe (O1)',
            to: 'Helix Hosting',
            amount: usdc(2400),
            requestId: 'req_070',
            option: 'STANDARD',
            reason: 'Due that day.',
            status: 'Final',
            confirmations: 64,
            verification: 'VERIFIED',
            txHash: h32('tx-070'),
            updatedAt: iso(-6 * DAY),
          },
          'pln_0419',
        ),
        step(
          2,
          {
            kind: 'REFILL',
            title: 'Refill Payroll Safe',
            from: 'Treasury Safe (T)',
            to: 'Payroll Safe (O2)',
            amount: usdc(490),
            reason: 'Bring O2 back to its target.',
            status: 'Unknown',
            txHash: h32('tx-refill-o2'),
            updatedAt: iso(-6 * DAY + 2 * MIN),
          },
          'pln_0419',
        ),
      ],
      validations: [
        {
          code: 'UNKNOWN_OPERATION_PENDING',
          decision: 'DENY',
          message:
            'A refill was sent but the RPC stopped answering before a receipt arrived. No new operation runs for O2 until its outcome is known.',
        },
      ],
      aiExplanation: {
        text: 'Helix was due the same day, so it went first. The refill restores the payroll buffer.',
        model: 'planner-v1',
        generatedAt: iso(-6 * DAY),
      },
      bindingConstraints: [],
    },
  ];

  const governance: Db['governance'] = [
    {
      id: 'gov_031',
      kind: 'ADD_PAYEE',
      title: 'Register a new payee for Northstar Analytics',
      summary:
        'Adds a second receiving wallet for Northstar Analytics. Payments to it stay blocked until the cooling period ends after execution.',
      status: 'AwaitingSignatures',
      treasuryId: 'trs_main',
      safeAddress: ADDR.safeT,
      safeLabel: 'Treasury Safe (T)',
      nonce: 31,
      threshold: 2,
      owners: OWNERS,
      signatures: [],
      signaturesHex: [],
      calls: [
        call('addPayee', [
          {
            name: 'payee',
            type: 'address',
            value: addr('payee-northstar-new'),
          },
          { name: 'label', type: 'string', value: 'Northstar Analytics' },
        ]),
      ],
      safeTxHash: h32('gov_031'),
      createdAt: iso(-2 * HOUR),
      createdBy: 'Minh Pham',
    },
    {
      id: 'gov_030',
      kind: 'CONFIGURE_MANDATE',
      title: 'Activate mandate v4',
      summary:
        'Raises the daily PAY limit from 10,000.00 to 12,000.00 USDC and extends the mandate by 30 days. Everything else is unchanged.',
      status: 'AwaitingSignatures',
      treasuryId: 'trs_main',
      safeAddress: ADDR.safeT,
      safeLabel: 'Treasury Safe (T)',
      nonce: 30,
      threshold: 2,
      owners: OWNERS,
      signatures: [{ owner: ADDR.an, at: iso(-50 * MIN) }],
      signaturesHex: [`0x${'11'.repeat(65)}`],
      calls: [
        call('configureMandate', [
          { name: 'version', type: 'uint32', value: '4' },
          { name: 'payDailyLimit', type: 'uint256', value: usdc(12000) },
          { name: 'payPerRequestLimit', type: 'uint256', value: usdc(2000) },
          {
            name: 'expiresAt',
            type: 'uint64',
            value: String(Math.floor((now() + 55 * DAY) / 1000)),
          },
        ]),
      ],
      diff: [
        {
          field: 'PAY daily limit',
          before: '10,000.00 USDC',
          after: '12,000.00 USDC',
          direction: 'LOOSER',
        },
        {
          field: 'Expires',
          before: 'in 25 days',
          after: 'in 55 days',
          direction: 'LOOSER',
        },
      ],
      safeTxHash: h32('gov_030'),
      createdAt: iso(-90 * MIN),
      createdBy: 'An Nguyen',
    },
    {
      id: 'gov_028',
      kind: 'CONFIGURE_MANDATE',
      title: 'Activate mandate v3',
      summary:
        'Lowered the per-request PAY limit from 5,000.00 to 2,000.00 USDC.',
      status: 'Executed',
      treasuryId: 'trs_main',
      safeAddress: ADDR.safeT,
      safeLabel: 'Treasury Safe (T)',
      nonce: 28,
      threshold: 2,
      owners: OWNERS,
      signatures: [
        { owner: ADDR.an, at: iso(-20 * DAY) },
        { owner: ADDR.quynh, at: iso(-20 * DAY + HOUR) },
      ],
      signaturesHex: [],
      calls: [
        call('configureMandate', [
          { name: 'version', type: 'uint32', value: '3' },
          { name: 'payPerRequestLimit', type: 'uint256', value: usdc(2000) },
        ]),
      ],
      diff: [
        {
          field: 'PAY per-request limit',
          before: '5,000.00 USDC',
          after: '2,000.00 USDC',
          direction: 'STRICTER',
        },
      ],
      safeTxHash: h32('gov_028'),
      createdAt: iso(-20 * DAY - HOUR),
      createdBy: 'An Nguyen',
      txHash: h32('tx-gov-028'),
    },
    {
      id: 'gov_027',
      kind: 'ADD_PAYEE',
      title: 'Register payee through a batch helper',
      summary:
        'Attempted to register two payees in one transaction through a MultiSend helper.',
      status: 'Failed',
      treasuryId: 'trs_main',
      safeAddress: ADDR.safeT,
      safeLabel: 'Treasury Safe (T)',
      nonce: 27,
      threshold: 2,
      owners: OWNERS,
      signatures: [
        { owner: ADDR.me, at: iso(-22 * DAY) },
        { owner: ADDR.an, at: iso(-22 * DAY) },
      ],
      signaturesHex: [],
      calls: [
        call(
          'multiSend',
          [{ name: 'transactions', type: 'bytes', value: '0x00…(2 calls)' }],
          {
            to: addr('multisend'),
            toLabel: 'MultiSend helper',
            operation: 1,
          },
        ),
      ],
      safeTxHash: h32('gov_027'),
      createdAt: iso(-22 * DAY),
      createdBy: 'Linh Tran',
      txHash: h32('tx-gov-027'),
      failureReason: 'Reverted: GS013 (inner call failed). No state changed.',
    },
    {
      id: 'gov_026',
      kind: 'CONFIGURE_MANDATE',
      title: 'Activate mandate v3 (first draft)',
      summary: 'An earlier draft of v3 with a 3,000.00 per-request limit.',
      status: 'Superseded',
      treasuryId: 'trs_main',
      safeAddress: ADDR.safeT,
      safeLabel: 'Treasury Safe (T)',
      nonce: 28,
      threshold: 2,
      owners: OWNERS,
      signatures: [{ owner: ADDR.an, at: iso(-21 * DAY) }],
      signaturesHex: [],
      calls: [
        call('configureMandate', [
          { name: 'version', type: 'uint32', value: '3' },
        ]),
      ],
      safeTxHash: h32('gov_026'),
      createdAt: iso(-21 * DAY),
      createdBy: 'An Nguyen',
      supersededBy: 'gov_028',
    },
  ];

  const activity: ActivityItem[] = [
    {
      id: 'act_1',
      at: iso(-12 * MIN),
      actor: 'agent',
      text: 'Proposed plan pln_0421: 1 refill and 2 payments, policy validated',
      href: 'plans/pln_0421',
    },
    {
      id: 'act_2',
      at: iso(-50 * MIN),
      actor: 'user',
      text: 'An Nguyen signed “Activate mandate v4” (1 of 2)',
    },
    {
      id: 'act_3',
      at: iso(-3 * HOUR),
      actor: 'agent',
      text: 'Screened new payee for Northstar Analytics: clear',
    },
    {
      id: 'act_4',
      at: iso(-5 * HOUR),
      actor: 'agent',
      text: 'Held LL-2026-512: 3,200.00 is over the 2,000.00 per-request limit',
    },
    {
      id: 'act_5',
      at: iso(-26 * HOUR),
      actor: 'chain',
      text: 'Supplied 12,000.00 USDC to Aave V3',
    },
  ];

  const db: Db = {
    timeScale: 1,
    session: readSession(),
    linkedWallets: [{ address: ADDR.me, linkedAt: iso(-30 * DAY) }],
    orgs: [
      {
        id: 'org_northwind',
        name: 'Northwind Labs',
        legalName: 'Northwind Labs Pte. Ltd.',
        country: 'SG',
        displayTz: 'Asia/Ho_Chi_Minh',
        soloMode: false,
        autoMatch: false,
        treasuries: [{ id: 'trs_main', name: 'Operating treasury' }],
      },
    ],
    orgMembers: {},
    moduleEnabled: { trs_main: ['T', 'O1', 'O2'] },
    members: [
      {
        userId: ME.id,
        name: ME.name,
        email: ME.email,
        roles: ['OWN', 'ADM', 'APR', 'OPR', 'FIN'],
        wallet: ADDR.me,
        status: 'Active',
      },
      {
        userId: APPROVER.id,
        name: APPROVER.name,
        email: APPROVER.email,
        roles: ['OWN', 'APR'],
        wallet: ADDR.an,
        status: 'Active',
      },
      {
        userId: MINH.id,
        name: MINH.name,
        email: 'minh@northwind.test',
        roles: ['OPR'],
        status: 'Active',
      },
      {
        userId: 'usr_quynh',
        name: 'Quynh Le',
        email: 'quynh@northwind.test',
        roles: ['OWN', 'FIN'],
        wallet: ADDR.quynh,
        status: 'Active',
      },
      {
        userId: 'usr_bao',
        name: 'Bao Vo',
        email: 'bao@northwind.test',
        roles: ['AUD'],
        status: 'Invited',
      },
    ],
    treasuries: {
      trs_main: {
        treasury: {
          id: 'trs_main',
          name: 'Operating treasury',
          chainId: 11155111,
          chainName: 'Sepolia',
          asset: ASSET,
          moduleAddress: ADDR.module,
          status: 'Active',
        },
        wallets: [
          {
            role: 'T',
            label: 'Treasury Safe',
            safeAddress: ADDR.safeT,
            balance: usdc(61440),
            buffer: usdc(23440),
            target: usdc(23440),
            threshold: 2,
            owners: OWNERS.map((owner) => owner.address),
          },
          {
            role: 'O1',
            label: 'Payments Safe',
            safeAddress: ADDR.safeO1,
            balance: usdc(4820),
            buffer: usdc(2000),
            target: usdc(6000),
            threshold: 1,
            owners: [ADDR.me],
          },
          {
            role: 'O2',
            label: 'Payroll Safe',
            safeAddress: ADDR.safeO2,
            balance: usdc(1010),
            buffer: usdc(500),
            target: usdc(1500),
            threshold: 1,
            owners: [ADDR.me],
          },
        ],
        coverage: {
          status: 'COMPLETE',
          acknowledged: false,
          missing: [],
          snapshotBlock: 6_914_300,
          details: [
            'The TreasuryPilot module is the only module enabled on all three Safes.',
            'No guard or fallback handler can move funds outside the mandate.',
          ],
        },
        mandate: { version: 3, status: 'Active', expiresAt: iso(25 * DAY) },
        budgets: [
          {
            action: 'PAY',
            usedToday: usdc(2600),
            dailyLimit: usdc(10000),
            perRequest: usdc(2000),
          },
          {
            action: 'REFILL',
            usedToday: usdc(1500),
            dailyLimit: usdc(12000),
            perRequest: usdc(2500),
          },
        ],
        staleness: {
          blockNumber: 6_914_208,
          observedAt: iso(-8_000),
          stale: false,
        },
        position: {
          safeUsdc: usdc(61440),
          aUsdc: usdc(101560),
          poolLiquidity: usdc(48_215_000),
          requiredReserve: {
            paymentReserve: usdc(18440),
            floor: usdc(5000),
            holds: '0',
            total: usdc(23440),
          },
          availableForSupply: usdc(38000),
          supplyApyBps: 342,
          lastAction: {
            kind: 'SUPPLY',
            amount: usdc(12000),
            at: iso(-26 * HOUR),
            explanation:
              'Safe balance exceeded the required reserve by more than the 10,000.00 supply threshold, and no payment was due within 48 hours.',
            txHash: h32('tx-supply'),
          },
        },
        queues: { approvals: 0, governance: 0, review: 0, reconciliation: 0 },
        activity,
        borrowProposalId: 'bor_007',
      },
    },
    mandates: {
      trs_main: [
        {
          id: 'mnd_v3',
          version: 3,
          status: 'Active',
          config: baseMandate(),
          createdAt: iso(-21 * DAY),
        },
        {
          id: 'mnd_v2',
          version: 2,
          status: 'Superseded',
          config: {
            ...baseMandate(),
            limits: {
              PAY: { perRequest: usdc(5000), daily: usdc(10000) },
              REFILL: { perRequest: usdc(2500), daily: usdc(12000) },
            },
          },
          createdAt: iso(-40 * DAY),
        },
      ],
    },
    payees,
    vendors,
    governance,
    requests,
    plans,
    reviewItems: [
      newReviewItem({
        id: 'rev_outflow',
        type: 'UNEXPECTED_OUTFLOW',
        primaryCode: 'OUTFLOW_NOT_IN_PLAN',
        treasuryId: 'trs_main',
        createdAt: iso(-2 * HOUR),
        slaDueAt: iso(46 * HOUR),
        reasonCodes: ['OUTFLOW_NOT_IN_PLAN'],
        completedSteps: [{ label: 'Circuit rule checked the balance change' }],
      }),
      newReviewItem({
        id: 'rev_512',
        type: 'NEEDS_AUTHORITY',
        primaryCode: 'OVER_PER_REQUEST_LIMIT',
        treasuryId: 'trs_main',
        createdAt: iso(-5 * HOUR),
        slaDueAt: iso(19 * HOUR),
        reasonCodes: ['OVER_PER_REQUEST_LIMIT'],
        completedSteps: [
          { label: 'Invoice approved' },
          { label: 'Policy engine checked the request' },
        ],
        requestId: 'req_512',
        requestVersion: 1,
      }),
      newReviewItem({
        id: 'rev_unknown',
        type: 'UNCERTAIN_TX',
        primaryCode: 'TX_UNKNOWN',
        treasuryId: 'trs_main',
        createdAt: iso(-6 * DAY),
        slaDueAt: iso(-5 * DAY),
        reasonCodes: ['NO_RECEIPT_OBSERVED'],
        completedSteps: [{ label: 'Transaction broadcast' }],
        planId: 'pln_0419',
        // Acknowledging is allowed only once the chain evidence settled the outcome.
        evidenceResolved: true,
      }),
      newReviewItem({
        id: 'rev_mismatch',
        type: 'DISCREPANCY',
        primaryCode: 'PAID_AMOUNT_MISMATCH',
        treasuryId: 'trs_main',
        createdAt: iso(-7 * DAY),
        slaDueAt: iso(-5 * DAY),
        reasonCodes: ['PAID_AMOUNT_MISMATCH'],
        requestId: 'req_056',
        requestVersion: 1,
      }),
    ],
    exceptions: {
      req_512: {
        // Like the API, no exception row exists until the Owner acts.
        exception: null,
        numbers: {
          amount: usdc(3200),
          cap: usdc(2000),
          dailyUsed: usdc(2600),
          dailyRemainingAfter: usdc(10000 - 2600 - 3200),
          valueIfGranted: null,
        },
        aiDraft: {
          source: 'AI',
          draft: {
            summary:
              'Lumen Legal’s retainer is 3,200.00 USDC, 1,200.00 above the 2,000.00 per-request limit.',
            reasons: [
              {
                text: 'The payee is registered and past cooling, and the invoice is approved.',
                evidence_ids: [],
              },
              {
                text: 'Today’s PAY total would be 5,800.00 of 10,000.00 after this payment.',
                evidence_ids: [],
              },
            ],
            alternatives: [
              'A one-time exception for this request only would let it pay on its due date.',
            ],
          },
        },
      },
    },
    reconciliations: [
      {
        id: 'rec_070',
        requestId: 'req_070',
        invoiceNumber: 'HX-2026-070',
        vendorName: 'Helix Hosting',
        amount: usdc(2400),
        paidAt: iso(-6 * DAY),
        txHash: h32('tx-070'),
        status: 'Unmatched',
        evidenceComplete: true,
        easUid: h32('eas-070'),
      },
      {
        id: 'rec_055',
        requestId: 'req_055',
        invoiceNumber: 'MS-2026-029',
        vendorName: 'Meridian Security',
        amount: usdc(1200),
        paidAt: iso(-8 * DAY),
        txHash: h32('tx-055'),
        status: 'Matched',
        evidenceComplete: true,
        easUid: h32('eas-055'),
        note: 'Matches bank-side statement line 14.',
      },
      {
        id: 'rec_056',
        requestId: 'req_056',
        invoiceNumber: 'OT-2026-198',
        vendorName: 'Orbit Telecom',
        amount: usdc(305),
        paidAt: iso(-8 * DAY),
        txHash: h32('tx-056'),
        status: 'Discrepancy',
        evidenceComplete: true,
        easUid: h32('eas-056'),
        note: 'Vendor statement shows 305.50.',
      },
      {
        id: 'rec_041',
        requestId: 'req_041',
        invoiceNumber: 'AC-2026-096',
        vendorName: 'Acurast Cloud',
        amount: usdc(1410),
        paidAt: iso(-13 * DAY),
        txHash: h32('tx-041'),
        status: 'Unmatched',
        evidenceComplete: false,
      },
    ],
    feePolicy: {
      active: {
        preset: 'NORMAL',
        maxFeeMultiplierBps: 20_000,
        tipPercentile: 50,
        perPlanThresholdWei: '5400000000000000',
        dailyBudgetWei: '10800000000000000',
        acceptedAt: iso(-20 * DAY),
      },
      proposal: {
        id: '0192b1c0-0000-7000-8000-000000000001',
        preset: 'NORMAL',
        maxFeeMultiplierBps: 20_000,
        tipPercentile: 50,
        perPlanThresholdWei: '5400000000000000',
        dailyBudgetWei: '10800000000000000',
        acceptedAt: null,
        proposedAt: iso(-1 * HOUR),
        basis: {
          avgPlanFee7dWei: '1800000000000000',
          p90PlanFee7dWei: '3100000000000000',
          plansPerDay7d: 4.5,
        },
      },
      spentTodayWei: '2100000000000000',
      day: iso(0).slice(0, 10),
      history: [
        {
          kind: 'POLICY',
          id: '0192b1c0-0000-7000-8000-0000000000a1',
          at: iso(-20 * DAY),
          by: 'Linh Tran',
          preset: 'NORMAL',
          maxFeeMultiplierBps: 20_000,
          perPlanThresholdWei: '5400000000000000',
          dailyBudgetWei: '10800000000000000',
        },
      ],
    },
    feeReviews: [
      {
        id: '0192b1c0-0000-7000-8000-0000000000b1',
        treasuryId: 'trs_main',
        planId: '0192b1c0-0000-7000-8000-0000000000c1',
        feeEstimateWei: '4200000000000000',
        slaDueAt: iso(3 * HOUR),
        type: 'FEE_APPROVAL',
        status: 'Open',
      },
    ],
    borrowProposals: [
      {
        id: 'bor_007',
        treasuryId: 'trs_main',
        reason:
          'A 9,500.00 USDC payroll run is due in 2 days. The Aave pool can return the full amount today, so this comparison is informational.',
        shortfall: usdc(9500),
        dueAt: dayIso(2),
        withdraw: {
          available: usdc(101560),
          cost: usdc(1, 78),
          note: 'Lost supply interest over 7 days at 3.42% APY.',
        },
        borrow: {
          amount: usdc(9500),
          aprBps: 512,
          cost7d: usdc(9, 33),
          note: 'Variable borrow interest over 7 days at 5.12% APR.',
        },
        healthFactorBefore: 0,
        healthFactorAfter: 8.4,
        recommended: 'WITHDRAW',
        status: 'Proposed',
      },
    ],
    notifications: [
      {
        id: 'ntf_1',
        at: iso(-12 * MIN),
        kind: 'execution',
        title: 'Plan ready to run',
        body: 'pln_0421 passed policy validation: 1 refill, 2 payments.',
        href: 'plans/pln_0421',
        read: false,
      },
      {
        id: 'ntf_2',
        at: iso(-50 * MIN),
        kind: 'governance',
        title: 'Your signature is needed',
        body: '“Activate mandate v4” has 1 of 2 signatures.',
        href: 'governance/gov_030',
        read: false,
      },
      {
        id: 'ntf_3',
        at: iso(-3 * HOUR),
        kind: 'approval',
        title: 'High-risk flag on NSA-2026-288',
        body: 'Payment address differs from the registered payee.',
        href: 'approvals/req_288',
        read: false,
      },
      {
        id: 'ntf_4',
        at: iso(-5 * HOUR),
        kind: 'review',
        title: 'Exception requested',
        body: 'LL-2026-512 is 1,200.00 over the per-request limit.',
        href: 'review?item=rev_512',
        read: true,
      },
      {
        id: 'ntf_5',
        at: iso(-26 * HOUR),
        kind: 'system',
        title: 'Supplied 12,000.00 USDC to Aave',
        body: 'Idle balance above the required reserve was supplied.',
        href: 'dashboard',
        read: true,
      },
    ],
    copilot: {},
    jobs: [],
    listeners: new Set(),
    eventSeq: 0,
  };
  return db;
}

function readSession(): User | null {
  try {
    const raw = window.sessionStorage.getItem(sessionKey);
    return raw ? (JSON.parse(raw) as User) : null;
  } catch {
    return null;
  }
}

export let db: Db = seed();

export const membersOf = (orgId: string) =>
  orgId === 'org_northwind' ? db.members : (db.orgMembers[orgId] ??= []);

export function resetDb(
  options: { signedIn?: boolean; timeScale?: number } = {},
) {
  db = seed();
  db.timeScale = options.timeScale ?? 1;
  if (options.signedIn) db.session = ME;
  refreshQueues();
}

/** Mock the planning worker's automatic plan creation after an eligible approval. */
export function planApprovedRequest(
  request: RequestDetail,
): PlanDetail | undefined {
  if (request.status !== 'Approved') return undefined;

  const existing = db.plans.find((plan) =>
    plan.steps.some((planStep) => planStep.requestId === request.id),
  );
  if (existing) return existing;

  const state = db.treasuries[request.treasuryId];
  const payLimit = state?.budgets.find((budget) => budget.action === 'PAY');
  if (
    !state ||
    !payLimit ||
    BigInt(request.amount) > BigInt(payLimit.perRequest)
  ) {
    return undefined;
  }
  if (
    BigInt(payLimit.usedToday) + BigInt(request.amount) >
    BigInt(payLimit.dailyLimit)
  ) {
    request.timeline.push({
      at: iso(),
      label: 'Approved but not planned: would exceed the daily PAY limit',
    });
    return undefined;
  }

  const optionKind = request.approvals.at(-1)?.option ?? 'STANDARD';
  const option = request.options.find(
    (candidate) => candidate.kind === optionKind,
  );
  if (!option) {
    request.timeline.push({
      at: iso(),
      label: 'Planning skipped: no matching option',
    });
    return undefined;
  }

  const id = `pln_${request.id.replace(/^req_/, '')}`;
  const plan: PlanDetail = {
    id,
    treasuryId: request.treasuryId,
    createdAt: iso(),
    status: 'Validated',
    plannerSource: 'RULE_BASED',
    expectedSaving: option.saving,
    totalAmount: option.amount,
    stepCount: 1,
    steps: [
      step(
        1,
        {
          kind: 'PAY',
          title: `Pay ${request.vendorName}`,
          from: 'Payments Safe (O1)',
          to: request.vendorName,
          amount: option.amount,
          requestId: request.id,
          option: optionKind,
          reason: 'The approved request is within the active PAY limit.',
        },
        id,
      ),
    ],
    validations: [
      {
        code: 'APPROVAL_VALID',
        decision: 'ALLOW',
        message: 'The request has a valid approver signature.',
      },
      {
        code: 'WITHIN_PER_REQUEST_LIMIT',
        decision: 'ALLOW',
        message: 'The request is within the active per-request PAY limit.',
      },
    ],
    bindingConstraints: [],
    attestation: {
      planHash: h32(id),
      signer: addr('policy-key'),
      signedAt: iso(),
    },
  };

  db.plans.unshift(plan);
  request.planId = id;
  request.status = 'Scheduled';
  request.timeline.push({ at: iso(), label: `Plan ${id} created` });
  logActivity(
    request.treasuryId,
    'agent',
    `Plan ${id} created for ${request.invoiceNumber}`,
    `plans/${id}`,
  );
  refreshQueues();
  emit('request', request.id);
  emit('plan', id);
  return plan;
}

export function setSession(user: User | null) {
  db.session = user;
  try {
    if (user) window.sessionStorage.setItem(sessionKey, JSON.stringify(user));
    else window.sessionStorage.removeItem(sessionKey);
  } catch {
    /* storage unavailable: the session lives for this page only */
  }
}

export const demoUser = ME;

/* ───────────── Clock, jobs and events ───────────── */

export function emit(type: ServerEvent['type'], entityId: string) {
  db.eventSeq += 1;
  const event: ServerEvent = { id: String(db.eventSeq), type, entityId };
  db.listeners.forEach((listener) => listener(event));
}

export function schedule(delayMs: number, run: () => void) {
  db.jobs.push({ at: now() + delayMs * db.timeScale, run });
}

/** Runs every job that is due. Called before each request and on a timer. */
export function tick() {
  for (;;) {
    const due = db.jobs
      .filter((job) => job.at <= now())
      .sort((a, b) => a.at - b.at)[0];
    if (!due) return;
    db.jobs.splice(db.jobs.indexOf(due), 1);
    due.run();
  }
}

export function notify(notification: Omit<Notification, 'id' | 'at' | 'read'>) {
  const item = {
    ...notification,
    id: `ntf_${now()}_${db.notifications.length}`,
    at: iso(),
    read: false,
  };
  db.notifications.unshift(item);
  emit('notification', item.id);
}

export function logActivity(
  treasuryId: string,
  actor: ActivityItem['actor'],
  text: string,
  href?: string,
) {
  db.treasuries[treasuryId]?.activity.unshift({
    id: `act_${now()}_${Math.random()}`,
    at: iso(),
    actor,
    text,
    href,
  });
}

/** An exception row as the API returns it. */
export function exceptionRow(
  requestId: string,
  status: NonNullable<ExceptionWire['exception']>['status'],
  init: Partial<NonNullable<ExceptionWire['exception']>> = {},
): NonNullable<ExceptionWire['exception']> {
  return {
    id: `exc_${requestId}`,
    requestId,
    status,
    governanceTxId: null,
    reason: null,
    expiry: iso(24 * HOUR),
    amount: '0',
    payee: h32('payee'),
    mandateVersion: 1,
    ...init,
  };
}

export type MockReviewItem = ReviewItem & { evidenceResolved?: boolean };
type RoleName = ReviewItem['assignedRoles'][number];
type ReviewAction = ReviewItem['allowedActions'][number];

export const roleNames: Record<Role, RoleName> = {
  OWN: 'Owner',
  APR: 'Approver',
  OPR: 'Operator',
  FIN: 'Finance',
  GRD: 'Guardian',
  ADM: 'OrgAdmin',
  AUD: 'Auditor',
};

/** The API routing table (recovery §8.3). */
export function reviewRoute(
  type: ReviewItem['type'],
  primaryCode: string,
): { roles: RoleName[]; actions: ReviewAction[] } {
  switch (type) {
    case 'NEEDS_AUTHORITY':
      return { roles: ['Owner'], actions: ['GRANT_EXCEPTION', 'CANCEL'] };
    case 'FEE_APPROVAL':
      return {
        roles: ['Finance', 'Operator', 'Owner'],
        actions: ['ACCEPT_FEE', 'DEFER'],
      };
    case 'UNCERTAIN_TX':
      return { roles: ['Operator'], actions: ['ACKNOWLEDGE'] };
    case 'DISCREPANCY':
      return {
        roles: ['Finance', 'Owner'],
        actions: ['ACKNOWLEDGE', 'MARK_MATCHED'],
      };
    case 'AI_REJECTED':
      return { roles: ['Operator'], actions: ['REPLAN', 'CANCEL'] };
    case 'INFRA':
      return { roles: ['Operator'], actions: ['RETRY'] };
    case 'UNEXPECTED_OUTFLOW':
      return { roles: ['Owner', 'Finance'], actions: ['ACKNOWLEDGE'] };
    case 'POLICY_BLOCK':
      return [
        'AMOUNT_CHANGED',
        'PAYEE_CHANGED',
        'APPROVAL_INVALID',
        'APPROVAL_EXPIRED',
      ].includes(primaryCode)
        ? {
            roles: ['Operator', 'Approver'],
            actions: ['EDIT_REQUEST', 'CANCEL'],
          }
        : { roles: ['Owner'], actions: ['REPLAN', 'CANCEL'] };
  }
}

/** An open review item as the API stores it; roles and SLA come from the routing table. */
export function newReviewItem(
  init: Pick<ReviewItem, 'id' | 'type' | 'primaryCode' | 'treasuryId'> &
    Partial<ReviewItem> & { evidenceResolved?: boolean },
): MockReviewItem {
  return {
    orgId: 'org_northwind',
    requestId: null,
    requestVersion: null,
    mandateVersionId: null,
    planId: null,
    feeEstimateWei: null,
    reasonCodes: [],
    completedSteps: [],
    assignedRoles: reviewRoute(init.type, init.primaryCode).roles,
    status: 'Open',
    slaDueAt: iso(24 * HOUR),
    createdAt: iso(0),
    resolvedBy: null,
    resolvedAt: null,
    resolution: null,
    note: null,
    version: 1,
    allowedActions: [],
    ...init,
  };
}

/** What this user may do on the item now, like the API's `_allowed_actions`. */
export function reviewView(item: MockReviewItem, roles: Role[]): ReviewItem {
  const { evidenceResolved, ...view } = item;
  const mine = roles.map((role) => roleNames[role]);
  const routed: ReviewAction[] = [
    ...reviewRoute(item.type, item.primaryCode).actions,
    // A partial plan can resume (recovery §7.2).
    ...(item.type === 'POLICY_BLOCK' && item.completedSteps.length > 0
      ? (['RETRY'] as const)
      : []),
  ];
  const visible = item.assignedRoles.some((role) => mine.includes(role));
  view.allowedActions =
    item.status === 'Open' && visible
      ? routed.filter(
          (action) =>
            item.type !== 'UNCERTAIN_TX' ||
            action !== 'ACKNOWLEDGE' ||
            evidenceResolved,
        )
      : [];
  return view;
}

export const reviewRoles = (orgId: string): Role[] =>
  membersOf(orgId).find((member) => member.userId === db.session?.id)?.roles ??
  [];

export function refreshQueues() {
  for (const state of Object.values(db.treasuries)) {
    state.queues = {
      approvals: db.requests.filter(
        (item) => item.status === 'AwaitingApproval',
      ).length,
      governance: db.governance.filter(
        (item) =>
          item.status === 'AwaitingSignatures' ||
          item.status === 'ReadyToExecute',
      ).length,
      review: db.reviewItems.filter((item) => item.status === 'Open').length,
      reconciliation: db.reconciliations.filter(
        (item) => item.status === 'Unmatched',
      ).length,
    };
  }
}

export function recountFlags(request: RequestDetail) {
  request.openFlags = request.flags.filter(
    (flag: Flag) => !flag.acknowledged,
  ).length;
  request.highFlagsUnacked = request.flags.filter(
    (flag) => flag.severity === 'HIGH' && !flag.acknowledged,
  ).length;
}

/* ───────────── Typed data the server builds (M16-D1) ───────────── */

export function approvalTypedData(request: RequestDetail): TypedData {
  const state = db.treasuries[request.treasuryId];
  const early = request.options.find((option) => option.kind === 'EARLY');
  const seconds = (value: string) =>
    Math.floor(new Date(value).getTime() / 1000);
  return {
    domain: {
      name: 'TreasuryPilot',
      version: '1',
      chainId: state.treasury.chainId,
      verifyingContract: state.treasury.moduleAddress,
    },
    types: {
      PaymentApproval: [
        { name: 'requestId', type: 'bytes32' },
        { name: 'invoiceHash', type: 'bytes32' },
        { name: 'fingerprint', type: 'bytes32' },
        { name: 'treasury', type: 'address' },
        { name: 'payingWallet', type: 'address' },
        { name: 'asset', type: 'address' },
        { name: 'payee', type: 'address' },
        { name: 'amount', type: 'uint256' },
        { name: 'earlyAmount', type: 'uint256' },
        { name: 'earlyPayBy', type: 'uint64' },
        { name: 'deadline', type: 'uint64' },
        { name: 'termsHash', type: 'bytes32' },
        { name: 'expiry', type: 'uint64' },
        { name: 'isFiat', type: 'bool' },
      ],
    },
    primaryType: 'PaymentApproval',
    message: {
      requestId: h32(request.id),
      invoiceHash: h32(`invoice-${request.id}-${request.revision}`),
      fingerprint: h32(
        `${request.vendorId}|${request.invoiceNumber}|${request.amount}`,
      ),
      treasury: state.treasury.moduleAddress,
      payingWallet: state.wallets.find((wallet) => wallet.role === 'O1')!
        .safeAddress,
      asset: state.treasury.asset.address,
      payee: request.payeeAddress ?? '',
      amount: request.amount,
      earlyAmount: early?.amount ?? '0',
      earlyPayBy: early ? seconds(early.payBy) : 0,
      deadline: seconds(request.dueDate!),
      termsHash: h32(JSON.stringify(request.terms)),
      expiry: seconds(request.dueDate!) + 7 * 24 * 3600,
      isFiat: false,
    },
  };
}

const ZERO: Hex = '0x0000000000000000000000000000000000000000';

export function safeTxTypedData(tx: GovernanceTxView): TypedData {
  const first = tx.calls[0];
  const state = db.treasuries[tx.treasuryId];
  return {
    domain: {
      chainId: state?.treasury.chainId ?? 11155111,
      verifyingContract: tx.safeAddress,
    },
    types: {
      EIP712Domain: [
        { name: 'chainId', type: 'uint256' },
        { name: 'verifyingContract', type: 'address' },
      ],
      SafeTx: [
        { name: 'to', type: 'address' },
        { name: 'value', type: 'uint256' },
        { name: 'data', type: 'bytes' },
        { name: 'operation', type: 'uint8' },
        { name: 'safeTxGas', type: 'uint256' },
        { name: 'baseGas', type: 'uint256' },
        { name: 'gasPrice', type: 'uint256' },
        { name: 'gasToken', type: 'address' },
        { name: 'refundReceiver', type: 'address' },
        { name: 'nonce', type: 'uint256' },
      ],
    },
    primaryType: 'SafeTx',
    message: {
      to: first.to,
      value: first.value,
      data: first.data,
      operation: first.operation,
      safeTxGas: '0',
      baseGas: '0',
      gasPrice: '0',
      gasToken: ZERO,
      refundReceiver: ZERO,
      nonce: tx.nonce,
    },
  };
}

/* ───────────── Governance ───────────── */

export function createGovernanceTx(
  input: Pick<
    GovernanceTxView,
    'kind' | 'title' | 'summary' | 'treasuryId' | 'calls'
  > & {
    diff?: DiffEntry[];
    effect?: () => void;
    safeRole?: 'T' | 'O1' | 'O2';
  },
) {
  const state = db.treasuries[input.treasuryId];
  const safe = state.wallets.find(
    (wallet) => wallet.role === (input.safeRole ?? 'T'),
  )!;
  const nonce =
    Math.max(
      0,
      ...db.governance
        .filter((tx) => tx.safeAddress === safe.safeAddress)
        .map((tx) => tx.nonce),
    ) + 1;
  const id = `gov_${String(nonce).padStart(3, '0')}_${db.governance.length}`;
  const tx: Db['governance'][number] = {
    ...input,
    id,
    status: 'AwaitingSignatures',
    safeAddress: safe.safeAddress,
    safeLabel: `${safe.label} (${safe.role})`,
    nonce,
    threshold: safe.threshold,
    owners: safe.owners.map((address) => ({
      address,
      name:
        OWNERS.find((owner) => owner.address === address)?.name ?? 'Safe owner',
    })),
    signatures: [],
    signaturesHex: [],
    safeTxHash: h32(id),
    createdAt: iso(),
    createdBy: db.session?.name ?? 'You',
  };
  db.governance.unshift(tx);
  refreshQueues();
  emit('governance', id);
  return tx;
}

export function markGovernanceSubmitted(
  tx: Db['governance'][number],
  txHash: Hex,
) {
  tx.status = 'Executing';
  tx.txHash = txHash;
  emit('governance', tx.id);
  schedule(3000, () => {
    tx.status = 'Executed';
    tx.effect?.();
    if (tx.kind === 'CONFIGURE_MANDATE' && !tx.effect) activateSeedMandate();
    if (tx.id === 'gov_031') startCooling('pay_northstar_new');
    logActivity(
      tx.treasuryId,
      'chain',
      `Executed “${tx.title}”`,
      `governance/${tx.id}`,
    );
    notify({
      kind: 'governance',
      title: 'Governance transaction executed',
      body: tx.title,
      href: `governance/${tx.id}`,
    });
    refreshQueues();
    emit('governance', tx.id);
  });
}

function activateSeedMandate() {
  const versions = db.mandates.trs_main;
  const config = {
    ...baseMandate(),
    limits: {
      ...baseMandate().limits,
      PAY: { perRequest: usdc(2000), daily: usdc(12000) },
    },
    expiresAt: iso(55 * DAY),
  };
  versions.forEach((version) => {
    if (version.status === 'Active') version.status = 'Superseded';
  });
  versions.unshift({
    id: 'mnd_v4',
    version: 4,
    status: 'Active',
    config,
    createdAt: iso(-90 * MIN),
  });
  applyMandate('trs_main', 4, config);
}

export function applyMandate(
  treasuryId: string,
  version: number,
  config: MandateConfig,
) {
  const state = db.treasuries[treasuryId];
  state.mandate = { version, status: 'Active', expiresAt: config.expiresAt };
  for (const budget of state.budgets) {
    budget.dailyLimit = config.limits[budget.action].daily;
    budget.perRequest = config.limits[budget.action].perRequest;
  }
  for (const buffer of config.buffers) {
    const wallet = state.wallets.find(
      (item) => item.safeAddress.toLowerCase() === buffer.wallet.toLowerCase(),
    );
    if (wallet) {
      wallet.buffer = buffer.minimum;
      if (buffer.target !== undefined) wallet.target = buffer.target;
    }
  }
}

export function startCooling(payeeId: string) {
  const payee = db.payees.find((item) => item.id === payeeId);
  if (!payee) return;
  payee.status = 'Cooling';
  payee.activeFrom = new Date(now() + 60_000 * db.timeScale).toISOString();
  schedule(60_000, () => {
    payee.status = 'Active';
    const vendor = db.vendors.find((item) => item.id === payee.vendorId);
    if (vendor) {
      vendor.payeeId = payee.id;
      vendor.payeeAddress = payee.address as Hex;
      vendor.payeeStatus = 'Active';
    }
    notify({
      kind: 'system',
      title: 'Payee is now active',
      body: `${vendorName(payee.vendorId)}: cooling period ended.`,
      href: 'payees',
    });
  });
}

/* ───────────── Plan execution ───────────── */

export function startExecution(plan: PlanDetail) {
  if (plan.steps.some((planStep) => planStep.amount === null)) return;
  plan.status = 'Executing';
  emit('plan', plan.id);
  const state = db.treasuries[plan.treasuryId];
  const set = (
    planStep: PlanStep,
    status: StepStatus,
    extra: Partial<PlanStep> = {},
  ) => {
    Object.assign(planStep, extra, { status, updatedAt: iso() });
    emit('operation', plan.id);
  };

  plan.steps.forEach((planStep, index) => {
    const base = index * 4200;
    schedule(base + 400, () => {
      set(planStep, 'Submitted', { txHash: h32(`tx-${planStep.id}-${now()}`) });
      const linked = db.requests.find((item) => item.id === planStep.requestId);
      if (linked) linked.status = 'InFlight';
    });
    schedule(base + 1400, () => set(planStep, 'Pending'));
    schedule(base + 2600, () =>
      set(planStep, 'Confirmed', { confirmations: 1 }),
    );
    schedule(base + 4000, () => {
      set(planStep, 'Verified', { confirmations: 3, verification: 'VERIFIED' });
      settleStep(plan, planStep, state);
    });
  });

  schedule(plan.steps.length * 4200 + 200, () => {
    plan.status = 'Completed';
    logActivity(
      plan.treasuryId,
      'agent',
      `Plan ${plan.id} finished: every step matched its available module event fields`,
      `plans/${plan.id}`,
    );
    notify({
      kind: 'execution',
      title: 'Plan completed',
      body: `${plan.id}: ${plan.steps.length} steps matched their available module event fields.`,
      href: `plans/${plan.id}`,
    });
    refreshQueues();
    emit('plan', plan.id);
  });
}

function settleStep(
  plan: PlanDetail,
  planStep: PlanStep,
  state: MockTreasuryState,
) {
  if (planStep.amount === null) return;
  const amount = BigInt(planStep.amount);
  const adjust = (role: string, delta: bigint) => {
    const wallet = state.wallets.find((item) => item.role === role);
    if (wallet) wallet.balance = (BigInt(wallet.balance) + delta).toString();
  };
  const budget = state.budgets.find(
    (item) => item.action === (planStep.kind === 'PAY' ? 'PAY' : 'REFILL'),
  );
  if (budget) budget.usedToday = (BigInt(budget.usedToday) + amount).toString();
  state.staleness = {
    blockNumber: state.staleness.blockNumber + 3,
    observedAt: iso(),
    stale: false,
  };

  if (planStep.kind === 'REFILL') {
    adjust('T', -amount);
    adjust('O1', amount);
    state.position.safeUsdc = state.wallets[0].balance;
    return;
  }
  adjust('O1', -amount);
  const linked = db.requests.find((item) => item.id === planStep.requestId);
  if (!linked) return;
  linked.status = 'Paid';
  linked.timeline.push({ at: iso(), label: 'Paid · 3 confirmations' });
  db.reconciliations.unshift({
    id: `rec_${linked.id.slice(4)}`,
    requestId: linked.id,
    invoiceNumber: linked.invoiceNumber,
    vendorName: linked.vendorName,
    amount: planStep.amount,
    paidAt: iso(),
    txHash: planStep.txHash!,
    status: 'Unmatched',
    evidenceComplete: true,
    easUid: h32(`eas-${linked.id}`),
  });
  emit('request', linked.id);
  void plan;
}

refreshQueues();
