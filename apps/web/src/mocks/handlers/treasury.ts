import { recoverTypedDataAddress } from 'viem';

import { formatUnits } from '@/lib/money';
import type {
  DiffEntry,
  Forecast,
  Hex,
  MandateConfig,
  MandateVersion,
  Payee,
  TreasuryStatus,
  TreasurySummary,
} from '@/lib/api/types';
import {
  ADDR,
  applyMandate,
  CHAINS,
  clearScreening,
  createGovernanceTx,
  DAY,
  db,
  emit,
  h32,
  iso,
  logActivity,
  markGovernanceSubmitted,
  oobPending,
  refreshQueues,
  safeTxTypedData,
  schedule,
  startCooling,
  usdc,
  vendorName,
} from '@/mocks/db';
import type { MockTreasuryState } from '@/mocks/db';

import {
  fail,
  find,
  isAddress,
  isLinked,
  isoNow,
  route,
  sameAddress,
} from './core';
import { requireOrg } from './identity';

const T = '/orgs/:orgId/treasuries/:tId';

const apiTreasuryStatus: Record<TreasuryStatus, TreasurySummary['status']> = {
  Setup: 'Draft',
  Active: 'Ready',
  PauseRequested: 'Paused',
  Paused: 'Paused',
  Revoked: 'Revoked',
};

/** GET treasury in the real API's shape, plus the dashboard extras TRS-009 adds. */
function treasuryView(state: MockTreasuryState) {
  const { treasury, wallets, coverage, ...extras } = state;
  return {
    ...extras,
    treasury: {
      id: treasury.id,
      chainId: treasury.chainId,
      assetId: treasury.asset.id,
      status: apiTreasuryStatus[treasury.status],
      coverage: {
        ...coverage,
        executionAllowed: coverage.executionAllowed ?? true,
      },
      moduleAddress: treasury.moduleAddress,
      createdAt: iso(-30 * DAY),
    },
    wallets: wallets.map((wallet) => ({
      id: `${treasury.id}_${wallet.role}`,
      role: wallet.role === 'T' ? 'SOURCE' : 'OPERATIONAL',
      label: wallet.label,
      safeAddress: wallet.safeAddress,
      owners: wallet.owners,
      threshold: wallet.threshold,
      balance: wallet.balance,
      buffer: wallet.buffer,
      target: wallet.target,
    })),
    warnings: [],
  };
}

function requireTreasury(params: Record<string, string>): MockTreasuryState {
  const org = requireOrg(params.orgId);
  if (!org.treasuries.some((item) => item.id === params.tId)) {
    fail(404, 'NOT_FOUND', 'Treasury was not found.');
  }
  return db.treasuries[params.tId];
}

const money = (value: string) => `${formatUnits(value, 6)} USDC`;

const walletName = (config: MandateConfig, wallet: string) =>
  wallet === ADDR.safeT ? 'T' : wallet === ADDR.safeO1 ? 'O1' : wallet;

/** Summary lines in the API's `{field, text}` shape. */
function describe(
  config: MandateConfig,
): Array<{ field: string; text: string }> {
  const line = (field: string, text: string) => ({ field, text });
  return [
    line(
      'actions',
      `The agent may ${config.actions.includes('PAY') ? 'pay approved requests' : 'not pay'} and ${config.actions.includes('REFILL') ? 'refill operational Safes' : 'not refill'}.`,
    ),
    line(
      'limits.PAY',
      `A single payment can be at most ${money(config.limits.PAY.perRequest)}; all payments in one UTC day at most ${money(config.limits.PAY.daily)}.`,
    ),
    line(
      'limits.REFILL',
      `A single refill can be at most ${money(config.limits.REFILL.perRequest)}; all refills in one UTC day at most ${money(config.limits.REFILL.daily)}.`,
    ),
    ...config.buffers.map((buffer) =>
      line(
        `buffers.${buffer.wallet}`,
        `Safe ${walletName(config, buffer.wallet)} never drops below ${money(buffer.minimum)}${buffer.target === undefined ? '' : ` and is refilled toward ${money(buffer.target)}`}.`,
      ),
    ),
    line(
      'approvers',
      `${config.approvers.length} approver wallet${config.approvers.length === 1 ? '' : 's'} can sign payment approvals.`,
    ),
    line(
      'expiresAt',
      `The mandate expires on ${new Date(config.expiresAt).toUTCString().slice(5, 16)}; after that the agent stops.`,
    ),
  ];
}

interface WireDiff {
  path: string;
  before: unknown;
  after: unknown;
  risk: 'looser' | 'stricter' | 'changed';
  marker: string;
  requiresConfirmation: boolean;
}

/** Diff entries in the API's shape: raw base-unit strings, lower-case risk. */
function diffMandate(
  before: MandateConfig | undefined,
  after: MandateConfig,
): WireDiff[] {
  if (!before) return [];
  const entries: WireDiff[] = [];
  const add = (
    path: string,
    a: unknown,
    b: unknown,
    risk: WireDiff['risk'],
    critical = false,
  ) =>
    entries.push({
      path,
      before: a,
      after: b,
      risk,
      marker: { looser: '▲', stricter: '▼', changed: '•' }[risk],
      requiresConfirmation: critical || risk === 'looser',
    });
  const amount = (
    path: string,
    a: string,
    b: string,
    higherIsLooser: boolean,
  ) => {
    if (a === b) return;
    const increased = BigInt(b) > BigInt(a);
    add(path, a, b, increased === higherIsLooser ? 'looser' : 'stricter');
  };
  for (const action of ['PAY', 'REFILL'] as const) {
    for (const field of ['perRequest', 'daily'] as const) {
      amount(
        `limits.${action}.${field}`,
        before.limits[action][field],
        after.limits[action][field],
        true,
      );
    }
  }
  for (const buffer of after.buffers) {
    const previous = before.buffers.find(
      (item) => item.wallet === buffer.wallet,
    );
    if (!previous) continue;
    amount(
      `buffers.${buffer.wallet}.minimum`,
      previous.minimum,
      buffer.minimum,
      false,
    );
    if (previous.target !== undefined && buffer.target !== undefined) {
      amount(
        `buffers.${buffer.wallet}.target`,
        previous.target,
        buffer.target,
        true,
      );
    }
  }
  const approvers = (config: MandateConfig) =>
    config.approvers.map((item) => item.toLowerCase()).sort();
  if (approvers(before).join() !== approvers(after).join()) {
    add(
      'approvers',
      approvers(before),
      approvers(after),
      after.approvers.length >= before.approvers.length ? 'looser' : 'stricter',
    );
  }
  if (before.expiresAt !== after.expiresAt) {
    add(
      'expiresAt',
      before.expiresAt,
      after.expiresAt,
      after.expiresAt > before.expiresAt ? 'looser' : 'stricter',
    );
  }
  for (const field of ['executor', 'guardian'] as const) {
    if (after[field] && before[field] !== after[field])
      add(field, before[field], after[field], 'changed', true);
  }
  return entries;
}

const mandateView = (treasuryId: string, version: MandateVersion) => ({
  ...version,
  treasuryId,
  configHash: h32(JSON.stringify(version.config)),
});

const governanceView = (tx: (typeof db.governance)[number]) => {
  const { effect: _effect, signaturesHex: _signatures, ...view } = tx;
  return view;
};

/** Mirrors the API: a hit (…dead) or provider error (…fa11) stores the payee ScreeningFailed, then 422/503. */
function screenOrFail(payee: Payee) {
  const tail = payee.address.toLowerCase();
  const result = tail.endsWith('dead')
    ? 'HIT'
    : tail.endsWith('fa11')
      ? 'ERROR'
      : null;
  if (!result) return;
  payee.screening = { ...clearScreening(isoNow()), result };
  payee.status = 'ScreeningFailed';
  if (result === 'HIT')
    fail(
      422,
      'SCREENING_HIT',
      'The address matched a sanctions screening list and is blocked.',
    );
  fail(
    503,
    'DATA_MISSING',
    'The screening provider did not answer; the payee is blocked.',
  );
}

export const treasuryHandlers = [
  route('get', '/orgs/:orgId/treasuries', ({ params }) => {
    const org = requireOrg(params.orgId);
    return {
      items: org.treasuries.flatMap(({ id }) => {
        const state = db.treasuries[id];
        if (!state) return [];
        const status = apiTreasuryStatus[state.treasury.status];
        return [
          {
            id,
            chainId: state.treasury.chainId,
            chainName: state.treasury.chainName,
            assetId: state.treasury.asset.id,
            assetSymbol: state.treasury.asset.symbol,
            assetDecimals: state.treasury.asset.decimals,
            assetIsTest: state.treasury.asset.isTest,
            status,
            coverage: state.coverage.status,
            coverageDetails: state.coverage.details,
            createdAt: iso(-30 * DAY),
          },
        ];
      }),
    };
  }),
  route<{ chainId: number; owners: string[]; threshold: number }>(
    'post',
    '/orgs/:orgId/safes/deploy-tx',
    ({ params }) => {
      requireOrg(params.orgId);
      fail(
        503,
        'SAFE_DEPLOYMENT_UNAVAILABLE',
        'The configured chain has no verified Safe proxy factory, v1.4.1 singleton, and fallback handler.',
      );
    },
  ),

  route<{
    name?: string;
    chainId: number;
    assetId: string;
    wallets: Array<{
      role: 'SOURCE' | 'OPERATIONAL';
      safeAddress: string;
      label: string;
    }>;
  }>(
    'post',
    '/orgs/:orgId/treasuries',
    ({ params, body }) => {
      const org = requireOrg(params.orgId);
      const chain = CHAINS.find((item) => item.chainId === body.chainId);
      const asset = chain?.assets.find((item) => item.id === body.assetId);
      if (!chain || !asset)
        fail(
          422,
          'UNSUPPORTED_ASSET',
          'This chain and asset are not supported.',
        );
      const errors = body.wallets.flatMap((wallet) => {
        const field = `wallets.${wallet.label}`;
        if (!isAddress(wallet.safeAddress))
          return [
            { field, message: 'Enter a 0x address with 40 hex characters.' },
          ];
        if (wallet.safeAddress.toLowerCase().endsWith('dead'))
          return [
            {
              field,
              message:
                'No Safe contract was found at this address on the selected chain.',
            },
          ];
        return [];
      });
      if (errors.length)
        fail(
          422,
          'NOT_A_SAFE',
          'One or more addresses are not Safes on this chain.',
          errors,
        );
      const addresses = body.wallets.map((wallet) =>
        wallet.safeAddress.toLowerCase(),
      );
      if (new Set(addresses).size !== addresses.length) {
        fail(422, 'DUPLICATE_WALLET', 'Each role needs a different Safe.');
      }
      const id = `trs_${org.id.slice(4, 10)}_${org.treasuries.length + 1}`;
      const owner = db.linkedWallets[0]?.address ?? ADDR.me;
      db.treasuries[id] = {
        treasury: {
          id,
          name: body.name?.trim() || 'Operating treasury',
          chainId: chain.chainId,
          chainName: chain.name,
          asset,
          moduleAddress: `0x${h32(`module-${id}`).slice(2, 42)}`,
          status: 'Setup',
        },
        wallets: body.wallets.map((wallet) => ({
          role:
            wallet.role === 'SOURCE'
              ? 'T'
              : wallet.label === 'O2'
                ? 'O2'
                : 'O1',
          label:
            wallet.role === 'SOURCE'
              ? 'Treasury Safe'
              : wallet.label === 'O2'
                ? 'Second operational Safe'
                : 'Payments Safe',
          safeAddress: wallet.safeAddress as Hex,
          balance: wallet.role === 'SOURCE' ? usdc(25000) : '0',
          buffer: '0',
          target: '0',
          threshold: 1,
          owners: [owner],
        })),
        coverage: {
          status: 'UNKNOWN',
          acknowledged: false,
          details: [],
          missing: [],
          snapshotBlock: null,
        },
        mandate: null,
        budgets: [],
        staleness: {
          blockNumber: 6_914_300,
          observedAt: isoNow(),
          stale: false,
        },
        position: {
          safeUsdc: usdc(25000),
          aUsdc: '0',
          poolLiquidity: usdc(48_215_000),
          requiredReserve: {
            paymentReserve: '0',
            floor: '0',
            holds: '0',
            total: '0',
          },
          availableForSupply: '0',
          supplyApyBps: 342,
          lastAction: {
            kind: 'NONE',
            amount: '0',
            at: isoNow(),
            explanation:
              'No liquidity action yet. Supplying starts after a mandate is active.',
          },
        },
        queues: { approvals: 0, governance: 0, review: 0, reconciliation: 0 },
        activity: [],
      };
      db.mandates[id] = [];
      org.treasuries.push({ id, name: db.treasuries[id].treasury.name });
      return { treasury: db.treasuries[id].treasury };
    },
    { status: 201 },
  ),

  route('get', T, ({ params }) => {
    const state = requireTreasury(params);
    refreshQueues();
    return treasuryView(state);
  }),

  route('post', `${T}/module/deploy-tx`, ({ params }) => {
    requireTreasury(params);
    const state = db.treasuries[params.tId];
    let txs = db.governance.filter(
      (tx) => tx.treasuryId === params.tId && tx.kind === 'DEPLOY_MODULE',
    );
    if (txs.length === 0) {
      txs = state.wallets
        .filter((safe) => ['T', 'O1', 'O2'].includes(safe.role))
        .map((safe) =>
          createGovernanceTx({
            kind: 'DEPLOY_MODULE',
            title:
              safe.role === 'T'
                ? 'Deploy and enable the TreasuryPilot module'
                : `Enable the TreasuryPilot module on ${safe.role}`,
            summary:
              safe.role === 'T'
                ? 'Deploys the module and enables it on the Treasury Safe.'
                : `Enables the deployed module on ${safe.role}.`,
            treasuryId: params.tId,
            safeRole: safe.role as 'T' | 'O1' | 'O2',
            calls: [
              {
                to: safe.safeAddress,
                toLabel: `${safe.label} (${safe.role})`,
                value: '0',
                operation: 0,
                method: 'enableModule',
                params: [
                  {
                    name: 'module',
                    type: 'address',
                    value: state.treasury.moduleAddress,
                  },
                ],
                data: `0x610b5925${'0'.repeat(24)}${state.treasury.moduleAddress.slice(2)}`,
              },
            ],
            effect: () => {
              const enabled = (db.moduleEnabled[params.tId] ??= []);
              if (!enabled.includes(safe.role)) enabled.push(safe.role);
            },
          }),
        );
    }
    return {
      governanceTx: governanceView(
        txs.find((tx) => tx.safeLabel.endsWith('(T)'))!,
      ),
      operationalGovernanceTxs: txs
        .filter((tx) => !tx.safeLabel.endsWith('(T)'))
        .map(governanceView),
      predictedModuleAddress: state.treasury.moduleAddress,
      status: 'ModulePending',
    };
  }),

  route('post', `${T}/coverage/refresh`, ({ params }) => {
    const state = requireTreasury(params);
    if (
      !state.wallets
        .filter((wallet) => ['T', 'O1', 'O2'].includes(wallet.role))
        .every((wallet) => db.moduleEnabled[params.tId]?.includes(wallet.role))
    )
      fail(
        409,
        'MODULE_NOT_ENABLED',
        'Execute the module transaction first, then check coverage.',
      );
    const partial = state.wallets.find((wallet) =>
      wallet.safeAddress.toLowerCase().endsWith('bad'),
    );
    state.coverage = partial
      ? {
          status: 'PARTIAL',
          acknowledged: false,
          missing: [],
          snapshotBlock: null,
          details: [
            `${partial.label} has another enabled module that can move funds without the mandate.`,
            'TreasuryPilot can still operate, but its limits do not bind that module.',
          ],
        }
      : {
          status: 'COMPLETE',
          acknowledged: false,
          missing: [],
          snapshotBlock: null,
          details: [
            'The TreasuryPilot module is the only module enabled on every Safe.',
            'No guard or fallback handler can move funds outside the mandate.',
          ],
        };
    return { coverage: state.coverage, details: state.coverage.details };
  }),

  route<{ reason?: string }>(
    'post',
    `${T}/coverage/acknowledge`,
    ({ params, body }) => {
      const state = requireTreasury(params);
      if (state.coverage.status === 'COMPLETE')
        fail(
          409,
          'COVERAGE_COMPLETE',
          'Coverage is complete. There is nothing to acknowledge.',
        );
      if (!body.reason?.trim())
        fail(422, 'VALIDATION', 'Explain why partial coverage is acceptable.');
      state.coverage.acknowledged = true;
      return { coverage: state.coverage };
    },
  ),

  route('get', `${T}/forecast`, ({ params, query }): Forecast => {
    const state = requireTreasury(params);
    const o1 =
      state.wallets.find((wallet) => wallet.role === 'O1') ?? state.wallets[0];
    let balance = BigInt(o1.balance);
    const open = db.requests.filter(
      (item) =>
        item.treasuryId === params.tId &&
        (['Approved', 'Scheduled', 'AwaitingApproval'].includes(item.status) ||
          (query.get('includeDrafts') === 'true' && item.status === 'Draft')),
    );
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(Date.now() + index * 86_400_000)
        .toISOString()
        .slice(0, 10);
      const outflow = open
        .filter((item) => item.dueDate?.slice(0, 10) === date)
        .reduce((total, item) => total + BigInt(item.amount), 0n);
      balance -= outflow;
      return {
        date,
        balance: balance.toString(),
        outflow: outflow.toString(),
        buffer: o1.buffer,
      };
    });
    const breach = days.find((day) => BigInt(day.balance) < BigInt(day.buffer));
    const source = state.wallets.find((wallet) => wallet.role === 'T');
    const cause =
      open.find((item) => item.dueDate?.slice(0, 10) === breach?.date) ??
      open[0];
    const wallets = state.wallets
      .filter((wallet) => wallet.role === 'O1' || wallet.role === 'O2')
      .map((wallet) => ({
        role: wallet.role,
        label: wallet.label,
        safeAddress: wallet.safeAddress,
        buffer: wallet.buffer,
        // Open requests all pay from O1; other wallets stay flat.
        days: days.map((day) => ({
          date: day.date,
          balance: wallet === o1 ? day.balance : wallet.balance,
        })),
      }));
    return {
      days,
      wallets,
      suggestedRefills:
        breach && source && cause
          ? [
              {
                date: breach.date,
                requestId: cause.id,
                sourceAddress: source.safeAddress,
                targetAddress: o1.safeAddress,
                amount: (BigInt(o1.target) - BigInt(breach.balance)).toString(),
              },
            ]
          : [],
      alerts: breach
        ? [
            {
              date: breach.date,
              message: `Without a refill, ${o1.label} drops below its minimum buffer on this day.`,
            },
          ]
        : [],
    };
  }),

  // Not in API_SPEC yet (ADR-019 D6): the borrow proposal read model.
  route('get', `${T}/borrow-proposals/:id`, ({ params }) => {
    requireTreasury(params);
    return find(
      db.borrowProposals,
      (item) => item.id === params.id && item.treasuryId === params.tId,
      'Borrow proposal',
    );
  }),

  // Reasons containing "sentinel-failed" or "no-sentinel" exercise the Guardian Safe fallbacks.
  route<{ reason?: string }>('post', `${T}/pause`, ({ params, body }) => {
    const state = requireTreasury(params);
    if (!body.reason?.trim())
      fail(
        422,
        'VALIDATION',
        'Give a reason for the pause. It is recorded in the audit log.',
      );
    const already = ['PauseRequested', 'Paused'].includes(
      state.treasury.status,
    );
    const sentinelFailed = body.reason.includes('sentinel-failed');
    const noSentinel = body.reason.includes('no-sentinel');
    const result = {
      backendPaused: true as const,
      onchainStatus:
        state.treasury.status === 'Paused' ? 'Effective' : 'Requested',
      onchain: already
        ? 'ALREADY_PAUSED'
        : sentinelFailed
          ? 'SENTINEL_FAILED'
          : noSentinel
            ? 'GUARDIAN_SAFE_TX_REQUIRED'
            : 'SENTINEL_SUBMITTED',
      sentinelTxHash: null as string | null,
      guardianTx: null as unknown,
      pendingTransactions: [] as unknown[],
    };
    state.treasury.status =
      state.treasury.status === 'Paused' ? 'Paused' : 'PauseRequested';
    state.treasury.pauseReason ??= body.reason;
    logActivity(params.tId, 'user', `Pause requested: ${body.reason}`);
    if (sentinelFailed || noSentinel) {
      result.guardianTx = {
        safeAddress: state.treasury.moduleAddress,
        call: {
          to: state.treasury.moduleAddress,
          value: '0',
          data: '0x8456cb59',
          operation: 0,
        },
      };
      return result;
    }
    if (!already) {
      result.sentinelTxHash = h32(`pause-${Date.now()}`);
      schedule(2500, () => {
        state.treasury.status = 'Paused';
        logActivity(params.tId, 'chain', 'Paused on-chain by the sentinel');
        emit('notification', 'pause');
      });
    }
    return result;
  }),

  route('get', `${T}/pause`, ({ params }) => {
    const state = requireTreasury(params);
    const status = state.treasury.status;
    return {
      backendPaused: status === 'PauseRequested' || status === 'Paused',
      onchainStatus:
        status === 'Paused'
          ? 'Effective'
          : status === 'PauseRequested'
            ? 'Requested'
            : 'NotRequested',
      effective: status === 'Paused',
      reason: state.treasury.pauseReason ?? null,
      treasuryStatus: status === 'Active' ? 'Ready' : status,
      pendingTransactions: [],
      guardianTx: null,
    };
  }),

  route('post', `${T}/resume-tx`, ({ params }) => {
    const state = requireTreasury(params);
    if (state.treasury.status === 'Active')
      fail(409, 'NOT_PAUSED', 'The treasury is not paused.');
    if (state.treasury.status !== 'Paused')
      fail(
        409,
        'PAUSE_NOT_EFFECTIVE',
        'The pause is not yet effective on-chain.',
      );
    const existing = db.governance.find(
      (tx) =>
        tx.treasuryId === params.tId &&
        tx.kind === 'RESUME' &&
        ['AwaitingSignatures', 'ReadyToExecute', 'Executing'].includes(
          tx.status,
        ),
    );
    if (existing) return { governanceTx: governanceView(existing) };
    const tx = createGovernanceTx({
      kind: 'RESUME',
      title: 'Resume the treasury',
      summary:
        'Lifts the on-chain pause. The agent can execute validated plans again under the active mandate.',
      treasuryId: params.tId,
      calls: [
        {
          to: state.treasury.moduleAddress,
          toLabel: 'TreasuryPilot module',
          value: '0',
          operation: 0,
          method: 'resume',
          params: [],
          data: '0x046f7da2',
        },
      ],
      effect: () => {
        state.treasury.status = 'Active';
        state.treasury.pauseReason = undefined;
      },
    });
    return { governanceTx: governanceView(tx) };
  }),

  route<{ confirmName?: string }>(
    'post',
    `${T}/revoke-tx`,
    ({ params, body }) => {
      const state = requireTreasury(params);
      const org = requireOrg(params.orgId);
      if (body.confirmName !== org.name)
        fail(
          422,
          'CONFIRMATION_MISMATCH',
          'Type the exact organization name to confirm.',
        );
      const tx = createGovernanceTx({
        kind: 'REVOKE',
        title: 'Revoke the treasury module',
        summary:
          'Permanently disables the module. This cannot be undone; the treasury must be redeployed.',
        treasuryId: params.tId,
        calls: [
          {
            to: state.treasury.moduleAddress,
            toLabel: 'TreasuryPilot module',
            value: '0',
            operation: 0,
            method: 'revoke',
            params: [],
            data: '0xb6549f75',
          },
        ],
        effect: () => {},
      });
      return { governanceTx: governanceView(tx) };
    },
  ),

  /* ───────────── Mandates ───────────── */

  route('get', `${T}/mandates`, ({ params }) => {
    requireTreasury(params);
    return {
      items: (db.mandates[params.tId] ?? []).map((item) =>
        mandateView(params.tId, item),
      ),
    };
  }),

  // Mirrors POST /mandates: the API body is the config; validation names `fields`.
  route<MandateConfig>(
    'post',
    `${T}/mandates`,
    ({ params, body }) => {
      requireTreasury(params);
      if (!body.approvers?.length)
        fail(422, 'NO_APPROVERS', 'At least one approver is required.');
      if (!/^0x[0-9a-fA-F]{40}$/.test(body.executor ?? ''))
        fail(
          422,
          'MANDATE_INCOMPLETE',
          'The mandate draft is missing required fields.',
          undefined,
          undefined,
          ['executor'],
        );
      for (const action of ['PAY', 'REFILL'] as const) {
        if (
          BigInt(body.limits[action].daily) <
          BigInt(body.limits[action].perRequest)
        ) {
          fail(
            422,
            'PER_REQUEST_ABOVE_DAILY',
            `The ${action} per-request limit exceeds its daily limit.`,
          );
        }
      }
      const below = body.buffers.find(
        (buffer) =>
          buffer.target !== undefined &&
          BigInt(buffer.target) < BigInt(buffer.minimum),
      );
      if (below) {
        fail(
          422,
          'TARGET_BELOW_BUFFER',
          `Target for ${below.wallet} is below its buffer.`,
        );
      }
      const versions = (db.mandates[params.tId] ??= []);
      const active = versions.find((item) => item.status === 'Active');
      const kept = versions.filter((item) => item.status !== 'Draft');
      const draft: MandateVersion = {
        id: `mnd_${Math.random().toString(36).slice(2, 10)}`,
        version: Math.max(0, ...versions.map((item) => item.version)) + 1,
        status: 'Draft',
        config: body,
        createdAt: isoNow(),
      };
      db.mandates[params.tId] = [draft, ...kept];
      const diff = diffMandate(active?.config, body);
      return {
        draft: mandateView(params.tId, draft),
        summary: describe(body),
        diff,
        requiresConfirmation: diff.some((entry) => entry.requiresConfirmation),
        bundlePreview: { calls: [] },
      };
    },
    { status: 201 },
  ),

  route('post', `${T}/mandates/:mandateId/governance-tx`, ({ params }) => {
    const state = requireTreasury(params);
    const versions = db.mandates[params.tId] ?? [];
    const draft = find(
      versions,
      (item) => item.id === params.mandateId,
      'Mandate version',
    );
    if (draft.status !== 'Draft')
      fail(
        409,
        'MANDATE_NOT_DRAFT',
        'Only a Draft mandate can be submitted for activation.',
      );
    const active = versions.find((item) => item.status === 'Active');
    draft.status = 'PendingActivation';
    const tx = createGovernanceTx({
      kind: 'CONFIGURE_MANDATE',
      title: `Activate mandate v${draft.version}`,
      summary: describe(draft.config)
        .slice(1, 3)
        .map((item) => item.text)
        .join(' '),
      treasuryId: params.tId,
      diff: diffMandate(active?.config, draft.config).map(
        (entry): DiffEntry => ({
          field: entry.path,
          before: String(entry.before),
          after: String(entry.after),
          direction:
            entry.risk === 'looser'
              ? 'LOOSER'
              : entry.risk === 'stricter'
                ? 'STRICTER'
                : 'NEUTRAL',
        }),
      ),
      calls: [
        {
          to: state.treasury.moduleAddress,
          toLabel: 'TreasuryPilot module',
          value: '0',
          operation: 0,
          method: 'configureMandate',
          params: [
            { name: 'version', type: 'uint32', value: String(draft.version) },
            {
              name: 'payPerRequestLimit',
              type: 'uint256',
              value: draft.config.limits.PAY.perRequest,
            },
            {
              name: 'payDailyLimit',
              type: 'uint256',
              value: draft.config.limits.PAY.daily,
            },
            {
              name: 'refillPerRequestLimit',
              type: 'uint256',
              value: draft.config.limits.REFILL.perRequest,
            },
            {
              name: 'refillDailyLimit',
              type: 'uint256',
              value: draft.config.limits.REFILL.daily,
            },
            {
              name: 'approvers',
              type: 'address[]',
              value: draft.config.approvers.join(', '),
            },
            {
              name: 'expiresAt',
              type: 'uint64',
              value: String(
                Math.floor(new Date(draft.config.expiresAt).getTime() / 1000),
              ),
            },
          ],
          data: h32(`mandate-${params.tId}-${draft.version}`),
        },
      ],
      effect: () => {
        versions.forEach((item) => {
          if (item.status === 'Active') item.status = 'Superseded';
        });
        draft.status = 'Active';
        if (!state.budgets.length) {
          state.budgets = [
            { action: 'PAY', usedToday: '0', dailyLimit: '0', perRequest: '0' },
            {
              action: 'REFILL',
              usedToday: '0',
              dailyLimit: '0',
              perRequest: '0',
            },
          ];
        }
        applyMandate(params.tId, draft.version, draft.config);
      },
    });
    // The API answers with the governance tx itself plus the mandate's new status.
    return {
      ...governanceView(tx),
      mandate: { id: draft.id, version: draft.version, status: draft.status },
    };
  }),

  /* ───────────── Payees ───────────── */

  route('get', `${T}/payees`, ({ params }) => {
    requireTreasury(params);
    return {
      items: db.payees.filter((payee) => payee.treasuryId === params.tId),
    };
  }),

  route<{ vendorId?: string; label?: string; address?: string }>(
    'post',
    `${T}/payees`,
    ({ params, body }) => {
      requireTreasury(params);
      if (!isAddress(body.address)) {
        // The real API reports a bad address as a coded problem, not field errors.
        fail(
          422,
          'ADDRESS_INVALID',
          'The address must be a valid EVM address.',
        );
      }
      const address = body.address;
      if (
        db.payees.some(
          (payee) =>
            payee.treasuryId === params.tId &&
            payee.status !== 'Deactivated' &&
            sameAddress(payee.address, address),
        )
      ) {
        fail(
          409,
          'PAYEE_EXISTS',
          'This address is already registered or proposed for this treasury.',
        );
      }
      const vendor = db.vendors.find((item) => item.id === body.vendorId);
      if (!vendor) fail(404, 'NOT_FOUND', 'Vendor not found.');
      const payee: Payee = {
        id: `pay_${db.payees.length}_${Date.now()}`,
        treasuryId: params.tId,
        vendorId: vendor.id,
        label: body.label?.trim() || 'Receiving wallet',
        address,
        status: 'Screening',
        screening: null,
        ...oobPending,
        registrationTxId: null,
        activeFrom: null,
        createdAt: isoNow(),
      };
      db.payees.unshift(payee);
      // The real API screens inside the POST and answers a hit with 422 after
      // persisting the payee as ScreeningFailed.
      screenOrFail(payee);
      // The delay keeps the Screening state observable in the mock.
      schedule(2000, () => {
        payee.screening = clearScreening(isoNow());
        payee.status = 'AwaitingOwner';
        emit('governance', payee.id);
      });
      return { payee };
    },
    { status: 201 },
  ),

  route<{ method?: string; note?: string }>(
    'post',
    `${T}/payees/:id/verify-oob`,
    ({ params, body }) => {
      requireTreasury(params);
      const payee = find(db.payees, (item) => item.id === params.id, 'Payee');
      if (payee.status !== 'AwaitingOwner' || payee.oobVerifiedAt)
        fail(
          409,
          'NOT_AWAITING_OWNER',
          'This payee is not waiting for an out-of-band check.',
        );
      if (!body.method || !body.note?.trim())
        fail(
          422,
          'VALIDATION',
          'Record how you confirmed the address with the vendor.',
        );
      Object.assign(payee, {
        oobMethod: body.method,
        oobNote: body.note,
        oobVerifiedBy: 'usr_linh',
        oobVerifiedAt: isoNow(),
      });
      return { payee };
    },
  ),

  route('post', `${T}/payees/:id/registration-tx`, ({ params }) => {
    const state = requireTreasury(params);
    const payee = find(db.payees, (item) => item.id === params.id, 'Payee');
    if (payee.screening?.result !== 'CLEAR' || !payee.oobVerifiedAt)
      fail(
        409,
        'SCREENING_NOT_CLEAR',
        'Screening must be clear and the address confirmed out of band first.',
      );
    if (payee.id === 'pay_northstar_new') {
      return {
        governanceTx: governanceView(
          db.governance.find((tx) => tx.id === 'gov_031')!,
        ),
      };
    }
    const name = vendorName(payee.vendorId);
    const tx = createGovernanceTx({
      kind: 'ADD_PAYEE',
      title: `Register payee ${name}`,
      summary: `Adds ${name} as a payee. Payments stay blocked until the cooling period ends after execution.`,
      treasuryId: params.tId,
      calls: [
        {
          to: state.treasury.moduleAddress,
          toLabel: 'TreasuryPilot module',
          value: '0',
          operation: 0,
          method: 'addPayee',
          params: [
            { name: 'payee', type: 'address', value: payee.address },
            { name: 'label', type: 'string', value: name },
          ],
          data: h32(`add-${payee.id}`),
        },
      ],
      effect: () => startCooling(payee.id),
    });
    return { governanceTx: governanceView(tx) };
  }),

  route<{ reason?: string }>(
    'post',
    `${T}/payees/:id/deactivation-tx`,
    ({ params, body }) => {
      const state = requireTreasury(params);
      const payee = find(db.payees, (item) => item.id === params.id, 'Payee');
      if (!body.reason?.trim())
        fail(422, 'VALIDATION', 'Give a reason for the deactivation.', [
          { field: 'reason', message: 'Give a reason.' },
        ]);
      if (payee.status !== 'Cooling' && payee.status !== 'Active')
        fail(
          409,
          'PAYEE_NOT_REGISTERED',
          'Only a registered payee can be deactivated on-chain.',
        );
      return { governanceTx: governanceView(deactivationTx(state, payee)) };
    },
    { status: 201 },
  ),

  route<{ address?: string; reason?: string }>(
    'post',
    `${T}/payees/:id/replace-address`,
    ({ params, body }) => {
      const state = requireTreasury(params);
      const old = find(db.payees, (item) => item.id === params.id, 'Payee');
      if (old.status !== 'Cooling' && old.status !== 'Active')
        fail(
          409,
          'PAYEE_NOT_REGISTERED',
          'Only a registered payee address can be replaced.',
        );
      if (!isAddress(body.address))
        fail(
          422,
          'ADDRESS_INVALID',
          'The replacement must be a valid address.',
          [{ field: 'address', message: 'Enter a valid 0x address.' }],
        );
      const address = body.address;
      if (sameAddress(old.address, address))
        fail(
          409,
          'ADDRESS_UNCHANGED',
          'Choose a different address to restart the payee cooling period.',
        );
      if (!body.reason?.trim())
        fail(422, 'VALIDATION', 'Give a reason for the change.', [
          { field: 'reason', message: 'Give a reason.' },
        ]);
      const payee: Payee = {
        ...old,
        id: `pay_${db.payees.length}_${Date.now()}`,
        address,
        status: 'AwaitingOwner',
        screening: clearScreening(isoNow()),
        ...oobPending,
        registrationTxId: null,
        activeFrom: null,
        createdAt: isoNow(),
      };
      db.payees.unshift(payee);
      screenOrFail(payee);
      return {
        payee,
        deactivationGovernanceTx: governanceView(deactivationTx(state, old)),
      };
    },
    { status: 201 },
  ),

  /* ───────────── Governance transactions (mandate module §6) ───────────── */

  route('get', '/orgs/:orgId/governance-txs', ({ params, query }) => {
    const org = requireOrg(params.orgId);
    const status = query.get('status');
    return {
      items: db.governance
        .filter((tx) =>
          org.treasuries.some((item) => item.id === tx.treasuryId),
        )
        .filter((tx) => !status || tx.status === status)
        .map(governanceView),
    };
  }),

  route('get', '/orgs/:orgId/governance-txs/:id', ({ params }) => {
    requireOrg(params.orgId);
    const tx = find(
      db.governance,
      (item) => item.id === params.id,
      'Governance transaction',
    );
    return { governanceTx: governanceView(tx), typedData: safeTxTypedData(tx) };
  }),

  route<{ signature: Hex }>(
    'post',
    '/orgs/:orgId/governance-txs/:id/signatures',
    async ({ params, body }) => {
      requireOrg(params.orgId);
      const tx = find(
        db.governance,
        (item) => item.id === params.id,
        'Governance transaction',
      );
      if (tx.status === 'Superseded')
        fail(
          409,
          'SUPERSEDED',
          'This transaction was superseded and can no longer be signed.',
        );
      if (tx.status !== 'AwaitingSignatures')
        fail(
          409,
          'NOT_AWAITING_SIGNATURES',
          'This transaction is not collecting signatures.',
        );
      const typedData = safeTxTypedData(tx);
      let signer: Hex;
      try {
        signer = await recoverTypedDataAddress({
          ...typedData,
          signature: body.signature,
        });
      } catch {
        fail(
          400,
          'SIGNATURE_INVALID',
          'The signature could not be verified against the SafeTx data.',
        );
      }
      const owner = tx.owners.find((item) => sameAddress(item.address, signer));
      if (!owner || !isLinked(signer))
        fail(
          403,
          'NOT_SAFE_OWNER',
          'The signing wallet is not an owner of this Safe, or it is not linked to your account.',
        );
      if (tx.signatures.some((item) => sameAddress(item.owner, signer)))
        fail(
          409,
          'ALREADY_SIGNED',
          'This wallet has already signed the transaction.',
        );
      tx.signatures.push({ owner: owner.address, at: isoNow() });
      tx.signaturesHex.push(body.signature);
      if (tx.signatures.length >= tx.threshold) tx.status = 'ReadyToExecute';
      logActivity(
        tx.treasuryId,
        'user',
        `${owner.name} signed “${tx.title}” (${tx.signatures.length} of ${tx.threshold})`,
        `governance/${tx.id}`,
      );
      emit('governance', tx.id);
      return { signatures: tx.signatures, status: tx.status };
    },
  ),

  route('get', '/orgs/:orgId/governance-txs/:id/exec-call', ({ params }) => {
    requireOrg(params.orgId);
    const tx = find(
      db.governance,
      (item) => item.id === params.id,
      'Governance transaction',
    );
    if (tx.status !== 'ReadyToExecute')
      fail(
        409,
        'NOT_READY',
        'The transaction does not have enough signatures yet.',
      );
    return {
      to: tx.safeAddress,
      data: `0x6a761202${h32(tx.id + tx.signaturesHex.join('')).slice(2)}`,
      value: '0',
    };
  }),

  route<{ txHash: Hex }>(
    'post',
    '/orgs/:orgId/governance-txs/:id/submitted',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const tx = find(
        db.governance,
        (item) => item.id === params.id,
        'Governance transaction',
      );
      if (tx.status !== 'ReadyToExecute')
        fail(409, 'NOT_READY', 'The transaction is not ready to execute.');
      markGovernanceSubmitted(tx, body.txHash);
      return { status: tx.status };
    },
  ),

  route('post', '/orgs/:orgId/governance-txs/:id/cancel', ({ params }) => {
    requireOrg(params.orgId);
    const tx = find(
      db.governance,
      (item) => item.id === params.id,
      'Governance transaction',
    );
    if (tx.status === 'Executing' || tx.status === 'Executed')
      fail(
        409,
        'ALREADY_SUBMITTED',
        'The transaction was already sent to the network.',
      );
    tx.status = 'Superseded';
    refreshQueues();
    return { status: tx.status };
  }),
];

function deactivationTx(
  state: ReturnType<typeof requireTreasury>,
  payee: Payee,
) {
  const name = vendorName(payee.vendorId);
  return createGovernanceTx({
    kind: 'DEACTIVATE_PAYEE',
    title: `Deactivate payee ${name}`,
    summary: `Removes ${name} (${payee.label}) from the payee registry. Requests to this address can no longer be paid.`,
    treasuryId: payee.treasuryId,
    calls: [
      {
        to: state.treasury.moduleAddress,
        toLabel: 'TreasuryPilot module',
        value: '0',
        operation: 0,
        method: 'removePayee',
        params: [{ name: 'payee', type: 'address', value: payee.address }],
        data: h32(`remove-${payee.id}`),
      },
    ],
    effect: () => {
      payee.status = 'Deactivated';
    },
  });
}
