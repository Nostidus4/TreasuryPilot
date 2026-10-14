import { recoverTypedDataAddress } from 'viem';

import { formatUnits } from '@/lib/money';
import type {
  DiffEntry,
  Forecast,
  Hex,
  MandateConfig,
  MandateDraft,
  MandateVersion,
  Payee,
  TreasuryState,
  TreasuryStatus,
  TreasurySummary,
} from '@/lib/api/types';
import {
  ADDR,
  applyMandate,
  CHAINS,
  createGovernanceTx,
  DAY,
  db,
  emit,
  h32,
  iso,
  logActivity,
  markGovernanceSubmitted,
  refreshQueues,
  safeTxTypedData,
  schedule,
  startCooling,
  usdc,
} from '@/mocks/db';

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

function requireTreasury(params: Record<string, string>): TreasuryState {
  const org = requireOrg(params.orgId);
  if (!org.treasuries.some((item) => item.id === params.tId)) {
    fail(404, 'NOT_FOUND', 'Treasury was not found.');
  }
  return db.treasuries[params.tId];
}

const money = (value: string) => `${formatUnits(value, 6)} USDC`;

function describe(config: MandateConfig): string[] {
  return [
    `The agent may ${config.actions.includes('PAY') ? 'pay approved requests' : 'not pay'} and ${config.actions.includes('REFILL') ? 'refill operational Safes' : 'not refill'}.`,
    `A single payment can be at most ${money(config.limits.PAY.perRequest)}; all payments in one UTC day at most ${money(config.limits.PAY.daily)}.`,
    `A single refill can be at most ${money(config.limits.REFILL.perRequest)}; all refills in one UTC day at most ${money(config.limits.REFILL.daily)}.`,
    ...config.buffers.map(
      (buffer) =>
        `Safe ${buffer.wallet} never drops below ${money(buffer.minimum)} and is refilled toward ${money(buffer.target)}.`,
    ),
    `${config.approvers.length} approver wallet${config.approvers.length === 1 ? '' : 's'} can sign payment approvals.`,
    `The mandate expires on ${new Date(config.expiresAt).toUTCString().slice(5, 16)}; after that the agent stops.`,
  ];
}

function diffMandate(
  before: MandateConfig | undefined,
  after: MandateConfig,
): DiffEntry[] {
  if (!before) return [];
  const entries: DiffEntry[] = [];
  const amount = (
    field: string,
    a: string,
    b: string,
    higherIsLooser: boolean,
  ) => {
    if (a === b) return;
    const increased = BigInt(b) > BigInt(a);
    entries.push({
      field,
      before: money(a),
      after: money(b),
      direction: increased === higherIsLooser ? 'LOOSER' : 'STRICTER',
    });
  };
  for (const action of ['PAY', 'REFILL'] as const) {
    amount(
      `${action} per-request limit`,
      before.limits[action].perRequest,
      after.limits[action].perRequest,
      true,
    );
    amount(
      `${action} daily limit`,
      before.limits[action].daily,
      after.limits[action].daily,
      true,
    );
  }
  for (const buffer of after.buffers) {
    const previous = before.buffers.find(
      (item) => item.wallet === buffer.wallet,
    );
    if (!previous) continue;
    amount(
      `${buffer.wallet} minimum buffer`,
      previous.minimum,
      buffer.minimum,
      false,
    );
    amount(
      `${buffer.wallet} target balance`,
      previous.target,
      buffer.target,
      false,
    );
  }
  const approvers = (config: MandateConfig) =>
    config.approvers
      .map((item) => item.toLowerCase())
      .sort()
      .join(',');
  if (approvers(before) !== approvers(after)) {
    entries.push({
      field: 'Approvers',
      before: `${before.approvers.length} wallets`,
      after: `${after.approvers.length} wallets`,
      direction:
        after.approvers.length > before.approvers.length
          ? 'LOOSER'
          : after.approvers.length < before.approvers.length
            ? 'STRICTER'
            : 'NEUTRAL',
    });
  }
  if (before.expiresAt.slice(0, 10) !== after.expiresAt.slice(0, 10)) {
    entries.push({
      field: 'Expires',
      before: before.expiresAt.slice(0, 10),
      after: after.expiresAt.slice(0, 10),
      direction: after.expiresAt > before.expiresAt ? 'LOOSER' : 'STRICTER',
    });
  }
  return entries;
}

const governanceView = (tx: (typeof db.governance)[number]) => {
  const { effect: _effect, signaturesHex: _signatures, ...view } = tx;
  return view;
};

export const treasuryHandlers = [
  route('get', '/orgs/:orgId/treasuries', ({ params }) => {
    const org = requireOrg(params.orgId);
    return {
      items: org.treasuries.flatMap(({ id }) => {
        const state = db.treasuries[id];
        if (!state) return [];
        const statuses: Record<TreasuryStatus, TreasurySummary['status']> = {
          Setup: 'Draft',
          Active: 'Ready',
          PauseRequested: 'Paused',
          Paused: 'Paused',
        };
        const status = statuses[state.treasury.status];
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
    return state;
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
      governanceTx: governanceView(txs.find((tx) => tx.safeLabel.endsWith('(T)'))!),
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

  // Not in API_SPEC yet (MDT-010): records the Guardian Safe and ends setup.
  route<{ safeAddress?: string }>(
    'post',
    `${T}/guardian`,
    ({ params, body }) => {
      const state = requireTreasury(params);
      if (!isAddress(body.safeAddress))
        fail(422, 'NOT_A_SAFE', 'Enter the Guardian Safe address.');
      if (
        state.coverage.status === 'UNKNOWN' ||
        (state.coverage.status === 'PARTIAL' && !state.coverage.acknowledged)
      ) {
        fail(
          409,
          'COVERAGE_INCOMPLETE',
          'Check coverage before finishing setup.',
        );
      }
      state.wallets = state.wallets.filter(
        (wallet) => wallet.role !== 'GUARDIAN',
      );
      state.wallets.push({
        role: 'GUARDIAN',
        label: 'Guardian Safe',
        safeAddress: body.safeAddress,
        balance: '0',
        buffer: '0',
        target: '0',
        threshold: 1,
        owners: [ADDR.guardian],
      });
      state.treasury.status = 'Active';
      logActivity(params.tId, 'user', 'Treasury setup completed');
      return { treasury: state.treasury };
    },
  ),

  route('get', `${T}/forecast`, ({ params }): Forecast => {
    const state = requireTreasury(params);
    const o1 =
      state.wallets.find((wallet) => wallet.role === 'O1') ?? state.wallets[0];
    let balance = BigInt(o1.balance);
    const open = db.requests.filter(
      (item) =>
        item.treasuryId === params.tId &&
        ['Approved', 'Scheduled', 'AwaitingApproval'].includes(item.status),
    );
    const days = Array.from({ length: 7 }, (_, index) => {
      const date = new Date(Date.now() + index * 86_400_000)
        .toISOString()
        .slice(0, 10);
      const outflow = open
        .filter((item) => item.dueDate.slice(0, 10) === date)
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
    return {
      days,
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

  route<{ reason?: string }>('post', `${T}/pause`, ({ params, body }) => {
    const state = requireTreasury(params);
    if (!body.reason?.trim())
      fail(
        422,
        'VALIDATION',
        'Give a reason for the pause. It is recorded in the audit log.',
      );
    state.treasury.status = 'PauseRequested';
    state.treasury.pauseReason = body.reason;
    const sentinelTxHash = h32(`pause-${Date.now()}`);
    logActivity(params.tId, 'user', `Pause requested: ${body.reason}`);
    schedule(2500, () => {
      state.treasury.status = 'Paused';
      logActivity(params.tId, 'chain', 'Paused on-chain by the sentinel');
      emit('notification', 'pause');
    });
    return {
      backendPaused: true,
      onchain: 'SENTINEL_SUBMITTED',
      sentinelTxHash,
    };
  }),

  route('post', `${T}/resume-tx`, ({ params }) => {
    const state = requireTreasury(params);
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

  /* ───────────── Mandates ───────────── */

  route('get', `${T}/mandates`, ({ params }) => {
    requireTreasury(params);
    return { items: db.mandates[params.tId] ?? [] };
  }),

  route<MandateConfig>(
    'post',
    `${T}/mandates`,
    ({ params, body }): MandateDraft => {
      requireTreasury(params);
      const errors: Array<{ field: string; message: string }> = [];
      if (!body.approvers?.length)
        errors.push({
          field: 'approvers',
          message: 'Add at least one approver wallet.',
        });
      for (const action of ['PAY', 'REFILL'] as const) {
        if (
          BigInt(body.limits[action].daily) <
          BigInt(body.limits[action].perRequest)
        ) {
          errors.push({
            field: `limits.${action}.daily`,
            message:
              'The daily limit cannot be lower than the per-request limit.',
          });
        }
      }
      if (errors.length)
        fail(422, 'MANDATE_INCOMPLETE', 'The mandate is incomplete.', errors);
      const below = body.buffers.find(
        (buffer) => BigInt(buffer.target) < BigInt(buffer.minimum),
      );
      if (below) {
        fail(
          422,
          'TARGET_BELOW_BUFFER',
          `The target for Safe ${below.wallet} is below its minimum buffer.`,
          [
            {
              field: `buffers.${below.wallet}.target`,
              message: 'Target must be at least the minimum buffer.',
            },
          ],
        );
      }
      const versions = (db.mandates[params.tId] ??= []);
      const active = versions.find((item) => item.status === 'Active');
      const kept = versions.filter((item) => item.status !== 'Draft');
      const draft: MandateVersion = {
        version: Math.max(0, ...kept.map((item) => item.version)) + 1,
        status: 'Draft',
        config: body,
        createdAt: isoNow(),
      };
      db.mandates[params.tId] = [draft, ...kept];
      return {
        draft,
        summary: describe(body),
        diff: diffMandate(active?.config, body),
      };
    },
    { status: 201 },
  ),

  route('post', `${T}/mandates/:version/activation-tx`, ({ params }) => {
    const state = requireTreasury(params);
    const versions = db.mandates[params.tId] ?? [];
    const draft = find(
      versions,
      (item) => String(item.version) === params.version,
      'Mandate version',
    );
    if (draft.status !== 'Draft')
      fail(409, 'NOT_DRAFT', 'Only a draft can be activated.');
    const active = versions.find((item) => item.status === 'Active');
    draft.status = 'PendingActivation';
    const tx = createGovernanceTx({
      kind: 'CONFIGURE_MANDATE',
      title: `Activate mandate v${draft.version}`,
      summary: describe(draft.config).slice(1, 3).join(' '),
      treasuryId: params.tId,
      diff: diffMandate(active?.config, draft.config),
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
        draft.activatedAt = isoNow();
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
    return { governanceTx: governanceView(tx) };
  }),

  /* ───────────── Payees ───────────── */

  route('get', `${T}/payees`, ({ params }) => {
    requireTreasury(params);
    return {
      items: db.payees.filter((payee) => payee.treasuryId === params.tId),
    };
  }),

  route<{
    vendorId?: string;
    vendorName?: string;
    label?: string;
    address?: string;
  }>(
    'post',
    `${T}/payees`,
    ({ params, body }) => {
      requireTreasury(params);
      if (!isAddress(body.address)) {
        fail(422, 'VALIDATION', 'Enter a valid payee address.', [
          {
            field: 'address',
            message: 'Enter a 0x address with 40 hex characters.',
          },
        ]);
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
      let vendor = db.vendors.find((item) => item.id === body.vendorId);
      if (!vendor) {
        const name = body.vendorName?.trim();
        if (!name)
          fail(
            422,
            'VALIDATION',
            'Choose a vendor or enter a new vendor name.',
            [{ field: 'vendorId', message: 'Choose a vendor.' }],
          );
        vendor = {
          id: `vnd_${db.vendors.length}`,
          name,
          payeeAddress: null,
          payeeStatus: null,
        };
        db.vendors.push(vendor);
      }
      const payee: Payee = {
        id: `pay_${db.payees.length}_${Date.now()}`,
        treasuryId: params.tId,
        vendorId: vendor.id,
        vendorName: vendor.name,
        label: body.label?.trim() || 'Receiving wallet',
        address,
        status: 'Screening',
        screening: { result: 'PENDING' },
        oobVerified: false,
        createdAt: isoNow(),
      };
      db.payees.unshift(payee);
      schedule(2000, () => {
        const hit = address.toLowerCase().endsWith('dead');
        payee.screening = {
          result: hit ? 'HIT' : 'CLEAR',
          checkedAt: isoNow(),
        };
        payee.status = hit ? 'ScreeningHit' : 'AwaitingVerification';
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
      if (payee.status !== 'AwaitingVerification')
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
      payee.oobVerified = true;
      payee.status = 'AwaitingRegistration';
      return { payee };
    },
  ),

  route('post', `${T}/payees/:id/registration-tx`, ({ params }) => {
    const state = requireTreasury(params);
    const payee = find(db.payees, (item) => item.id === params.id, 'Payee');
    if (payee.screening.result !== 'CLEAR' || !payee.oobVerified)
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
    const tx = createGovernanceTx({
      kind: 'ADD_PAYEE',
      title: `Register payee ${payee.vendorName}`,
      summary: `Adds ${payee.vendorName} as a payee. Payments stay blocked until the cooling period ends after execution.`,
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
            { name: 'label', type: 'string', value: payee.vendorName },
          ],
          data: h32(`add-${payee.id}`),
        },
      ],
      effect: () => startCooling(payee.id),
    });
    return { governanceTx: governanceView(tx) };
  }),

  route('post', `${T}/payees/:id/deactivation-tx`, ({ params }) => {
    const state = requireTreasury(params);
    const payee = find(db.payees, (item) => item.id === params.id, 'Payee');
    const tx = createGovernanceTx({
      kind: 'DEACTIVATE_PAYEE',
      title: `Deactivate payee ${payee.vendorName}`,
      summary: `Removes ${payee.vendorName} (${payee.label}) from the payee registry. Requests to this address can no longer be paid.`,
      treasuryId: params.tId,
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
    return { governanceTx: governanceView(tx) };
  }),

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
