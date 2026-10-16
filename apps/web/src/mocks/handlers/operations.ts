import { HttpResponse, sse, type RequestHandler } from 'msw';

import { formatUnits } from '@/lib/money';
import type {
  CopilotMessage,
  FeePresetId,
  OperationsMetrics,
  SavingsMetrics,
  ServerEvent,
} from '@/lib/api/types';
import {
  createGovernanceTx,
  db,
  h32,
  refreshQueues,
  exceptionRow,
  reviewRoles,
  reviewView,
  roleNames,
  startExecution,
  tick,
  usdc,
} from '@/mocks/db';

import { fail, find, isoNow, route } from './core';
import { requireOrg } from './identity';
import { governanceView } from './treasury';

const northwind = (orgId: string) => orgId === 'org_northwind';
const money = (value: string) => `${formatUnits(value, 6)} USDC`;

function planSummary(plan: (typeof db.plans)[number]) {
  const {
    steps: _s,
    validations: _v,
    aiExplanation: _a,
    bindingConstraints: _b,
    attestation: _t,
    ...summary
  } = plan;
  return summary;
}

function answer(
  question: string,
  treasuryId: string,
): Omit<CopilotMessage, 'id' | 'role'> {
  const state = db.treasuries[treasuryId] ?? Object.values(db.treasuries)[0];
  const base = `/o/org_northwind/t/${state.treasury.id}`;
  const text = question.toLowerCase();
  if (/(runway|buffer|liquid|balance|cash)/.test(text)) {
    const o1 =
      state.wallets.find((wallet) => wallet.role === 'O1') ?? state.wallets[0];
    return {
      content: `${o1.label} holds ${money(o1.balance)} against a minimum buffer of ${money(o1.buffer)} and a target of ${money(o1.target)}. The Treasury Safe holds ${money(state.position.safeUsdc)} and ${money(state.position.aUsdc)} is supplied to Aave. The required reserve is ${money(state.position.requiredReserve.total)}.`,
      citations: [{ label: 'Treasury snapshot', href: base }],
    };
  }
  if (/(why|held|limit|exception|lumen)/.test(text)) {
    const cap = state.budgets.find((budget) => budget.action === 'PAY');
    return {
      content: `LL-2026-512 from Lumen Legal is held because its amount, 3,200.00 USDC, is above the per-request PAY limit of ${cap ? money(cap.perRequest) : 'the mandate'}. The policy decision is NEEDS_APPROVAL with reason code OVER_PER_REQUEST_LIMIT. It can only be paid if the Safe owners grant a one-time exception.`,
      citations: [
        {
          label: 'Request LL-2026-512',
          href: '/o/org_northwind/requests/req_512',
        },
        { label: 'Review item', href: '/o/org_northwind/review?item=rev_512' },
      ],
    };
  }
  if (/(plan|next|schedule|pay)/.test(text)) {
    const plan = db.plans[0];
    const total = plan.totalAmount ? money(plan.totalAmount) : 'unavailable';
    const saving = plan.expectedSaving
      ? money(plan.expectedSaving)
      : 'unavailable';
    return {
      content: `The latest plan is ${plan.id} (${plan.status}). It has ${plan.steps.length} steps totalling ${total} and an expected saving of ${saving} from early-payment discounts.`,
      citations: [
        { label: `Plan ${plan.id}`, href: `${base}/plans/${plan.id}` },
      ],
    };
  }
  return {
    content:
      'I can answer questions about balances and buffers, why a request is held, and what the current plan will do. I only read data: I cannot approve, sign or move funds.',
    citations: [],
  };
}

export const operationHandlers: RequestHandler[] = [
  route('get', '/orgs/:orgId/treasuries/:tId/plans', ({ params }) => {
    requireOrg(params.orgId);
    return {
      items: db.plans
        .filter((plan) => plan.treasuryId === params.tId)
        .map(planSummary),
    };
  }),

  route('get', '/orgs/:orgId/plans/:pId', ({ params }) => {
    requireOrg(params.orgId);
    return find(db.plans, (plan) => plan.id === params.pId, 'Plan');
  }),

  route(
    'post',
    '/orgs/:orgId/treasuries/:tId/run-now',
    ({ params }) => {
      requireOrg(params.orgId);
      const state = db.treasuries[params.tId];
      if (
        state.treasury.status === 'Paused' ||
        state.treasury.status === 'PauseRequested'
      ) {
        fail(
          409,
          'TREASURY_PAUSED',
          'The treasury is paused. Resume it before running a plan.',
        );
      }
      if (
        state.coverage.status !== 'COMPLETE' &&
        !state.coverage.acknowledged
      ) {
        fail(
          409,
          'COVERAGE_INCOMPLETE',
          'Coverage is incomplete and has not been acknowledged.',
        );
      }
      const plan = db.plans.find(
        (item) => item.treasuryId === params.tId && item.status === 'Validated',
      );
      // The API has no NOTHING_TO_RUN: it enqueues a cycle and the planner finds the work.
      if (!plan) return { jobId: `job_${crypto.randomUUID()}` };
      startExecution(plan);
      return { jobId: `job_${plan.id}` };
    },
    { status: 202 },
  ),

  route('get', '/orgs/:orgId/review-items', ({ params, query }) => {
    requireOrg(params.orgId);
    const type = query.get('type');
    if (type === 'FEE_APPROVAL')
      return { items: northwind(params.orgId) ? db.feeReviews : [] };
    const status = query.get('status');
    const roles = reviewRoles(params.orgId);
    return {
      items: northwind(params.orgId)
        ? db.reviewItems
            .map((item) => reviewView(item, roles))
            .filter(
              (item) =>
                (!status || item.status === status) &&
                (!type || item.type === type) &&
                // Like the API, an item is visible only to its routed roles.
                item.assignedRoles.some((role) =>
                  roles.map((code) => roleNames[code]).includes(role),
                ),
            )
        : [],
    };
  }),

  route<{ action: string; note?: string; version?: number }>(
    'post',
    '/orgs/:orgId/review-items/:id/actions',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const item = find(
        db.reviewItems,
        (entry) => entry.id === params.id,
        'Review item',
      );
      if (!Number.isInteger(body.version) || (body.version ?? 0) < 1)
        fail(422, 'VALIDATION', 'version is required.');
      if (item.status !== 'Open' || body.version !== item.version)
        fail(
          409,
          'STALE_ITEM',
          'This item was already handled. Reload the queue.',
        );
      const roles = reviewRoles(params.orgId);
      const allowed: string[] = reviewView(item, roles).allowedActions;
      if (!allowed.includes(body.action))
        fail(
          409,
          'ACTION_NOT_ALLOWED',
          'The action is not allowed for this item.',
        );
      item.version += 1;
      if (body.note) item.note = body.note;
      if (body.action !== 'DEFER') {
        item.status = 'Resolved';
        item.resolution = body.action;
        item.resolvedBy = db.session!.id;
        item.resolvedAt = isoNow();
      }
      refreshQueues();
      return { item: reviewView(item, roles) };
    },
  ),

  route('get', '/orgs/:orgId/requests/:rId/exception', ({ params }) => {
    requireOrg(params.orgId);
    const exception = db.exceptions[params.rId];
    if (!exception)
      fail(404, 'NOT_FOUND', 'There is no exception request for this payment.');
    return exception;
  }),

  route<{ expiryHours?: number }>(
    'post',
    '/orgs/:orgId/requests/:rId/exception/grant-tx',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const detail = db.exceptions[params.rId];
      if (!detail)
        fail(
          404,
          'NOT_FOUND',
          'There is no exception request for this payment.',
        );
      const request = find(
        db.requests,
        (item) => item.id === params.rId,
        'Request',
      );
      const { numbers } = detail;
      const overBy = BigInt(numbers.amount) - BigInt(numbers.cap);
      if (overBy <= 0n) {
        fail(
          409,
          'NOT_OVER_CAP',
          'This request is within the per-request limit; no exception is needed.',
        );
      }
      const state = db.treasuries[request.treasuryId];
      const tx = createGovernanceTx({
        kind: 'GRANT_EXCEPTION',
        title: `Grant one-time exception for ${request.invoiceNumber}`,
        summary: `Allows a single payment of ${money(request.amount)} to ${request.vendorName}, ${money(overBy.toString())} above the per-request limit. The exception applies to this request only and expires in ${body.expiryHours ?? 24} hours.`,
        treasuryId: request.treasuryId,
        calls: [
          {
            to: state.treasury.moduleAddress,
            toLabel: 'TreasuryPilot module',
            value: '0',
            operation: 0,
            method: 'grantException',
            params: [
              { name: 'requestId', type: 'bytes32', value: h32(request.id) },
              { name: 'amount', type: 'uint256', value: request.amount },
              {
                name: 'expiry',
                type: 'uint64',
                value: String(
                  Math.floor(Date.now() / 1000) +
                    (body.expiryHours ?? 24) * 3600,
                ),
              },
            ],
            data: h32(`exception-${request.id}`),
          },
        ],
        effect: () => {
          detail.exception = exceptionRow(request.id, 'Granted');
          const item = db.reviewItems.find(
            (entry) =>
              entry.requestId === request.id &&
              entry.type === 'NEEDS_AUTHORITY',
          );
          if (item) {
            item.status = 'Resolved';
            item.resolution = 'GRANT_EXCEPTION';
            item.note = 'Exception granted on-chain.';
            item.resolvedAt = isoNow();
          }
          request.status = 'Scheduled';
        },
      });
      detail.exception = exceptionRow(request.id, 'Proposed', {
        governanceTxId: tx.id,
        amount: request.amount,
      });
      return { governanceTx: governanceView(tx) };
    },
  ),

  route<{ reason?: string }>(
    'post',
    '/orgs/:orgId/requests/:rId/exception/reject',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const detail = db.exceptions[params.rId];
      if (!detail)
        fail(
          404,
          'NOT_FOUND',
          'There is no exception request for this payment.',
        );
      if (!body.reason?.trim())
        fail(422, 'VALIDATION', 'Give a reason for the rejection.');
      detail.exception = exceptionRow(params.rId, 'Rejected', {
        reason: body.reason,
      });
      const item = db.reviewItems.find(
        (entry) =>
          entry.requestId === params.rId && entry.type === 'NEEDS_AUTHORITY',
      );
      if (item) {
        item.status = 'Resolved';
        item.resolution = 'CANCEL';
        item.note = body.reason;
        item.resolvedAt = isoNow();
      }
      refreshQueues();
      return { exception: detail.exception };
    },
  ),

  /* ───────────── Reconciliation ───────────── */

  route('get', '/orgs/:orgId/reconciliations', ({ params, query }) => {
    requireOrg(params.orgId);
    const status = query.get('status');
    return {
      items: northwind(params.orgId)
        ? db.reconciliations.filter((item) => !status || item.status === status)
        : [],
    };
  }),

  route<{ note?: string }>(
    'post',
    '/orgs/:orgId/reconciliations/:id/match',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const item = find(
        db.reconciliations,
        (entry) => entry.id === params.id,
        'Reconciliation',
      );
      if (!item.evidenceComplete)
        fail(
          409,
          'EVIDENCE_INCOMPLETE',
          'The evidence bundle is incomplete: the payment receipt attestation is missing.',
        );
      item.status = 'Matched';
      item.note = body.note?.trim() || undefined;
      refreshQueues();
      return { reconciliation: item };
    },
  ),

  route<{ note?: string }>(
    'post',
    '/orgs/:orgId/reconciliations/:id/discrepancy',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const item = find(
        db.reconciliations,
        (entry) => entry.id === params.id,
        'Reconciliation',
      );
      if (!body.note?.trim())
        fail(422, 'VALIDATION', 'Describe the discrepancy.');
      item.status = 'Discrepancy';
      item.note = body.note.trim();
      refreshQueues();
      return { reconciliation: item };
    },
  ),

  route('get', '/orgs/:orgId/exports/reconciliation.csv', ({ params }) => {
    requireOrg(params.orgId);
    const rows = [
      'invoice_number,vendor,amount_base_units,asset,network,paid_at,tx_hash,status,note',
      ...db.reconciliations.map((item) =>
        [
          item.invoiceNumber,
          item.vendorName,
          item.amount,
          'USDC',
          'Sepolia',
          item.paidAt,
          item.txHash,
          item.status,
          (item.note ?? '').replace(/,/g, ';'),
        ].join(','),
      ),
    ];
    return new HttpResponse(rows.join('\n'), {
      headers: { 'Content-Type': 'text/csv' },
    });
  }),

  /* ───────────── Fee policy (mandate module §6) ───────────── */

  route('get', '/orgs/:orgId/treasuries/:tId/fee-policy', ({ params }) => {
    requireOrg(params.orgId);
    return db.feePolicy;
  }),

  route<{ proposalId?: string; preset?: FeePresetId }>(
    'post',
    '/orgs/:orgId/treasuries/:tId/fee-policy/accept',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const proposal = db.feePolicy.proposal;
      if (!proposal || proposal.id !== body.proposalId)
        fail(409, 'FEE_PROPOSAL_STALE', 'Reload the current fee proposal.');
      const { id, basis, proposedAt, ...row } = proposal;
      void basis;
      void proposedAt;
      const accepted = {
        ...row,
        preset: body.preset ?? 'NORMAL',
        acceptedAt: new Date().toISOString(),
      };
      db.feePolicy.active = accepted;
      db.feePolicy.proposal = null;
      db.feePolicy.history.unshift({
        kind: 'POLICY',
        id,
        at: accepted.acceptedAt,
        by: 'You',
        preset: accepted.preset,
        maxFeeMultiplierBps: accepted.maxFeeMultiplierBps,
        perPlanThresholdWei: accepted.perPlanThresholdWei,
        dailyBudgetWei: accepted.dailyBudgetWei,
      });
      return { active: accepted };
    },
  ),

  ...(['accept', 'defer'] as const).map((action) =>
    route('post', `/orgs/:orgId/plans/:pId/fee/${action}`, ({ params }) => {
      requireOrg(params.orgId);
      const held = db.feeReviews.find((item) => item.planId === params.pId);
      if (!held)
        fail(404, 'FEE_REVIEW_NOT_FOUND', 'The held plan is unavailable.');
      if (action === 'accept') {
        db.feeReviews = db.feeReviews.filter((item) => item !== held);
        db.feePolicy.history.unshift({
          kind: 'PLAN_FEE',
          id: `fee_${held.id}`,
          at: new Date().toISOString(),
          by: 'You',
          planId: params.pId,
          estimatedFeeWei: held.feeEstimateWei ?? '0',
          acceptedCapWei: held.feeEstimateWei ?? '0',
        });
      }
      return { planId: params.pId };
    }),
  ),

  /* ───────────── Metrics ───────────── */

  route(
    'get',
    '/orgs/:orgId/metrics/operations',
    ({ params }): { metrics: OperationsMetrics } => {
      requireOrg(params.orgId);
      const series = Array.from({ length: 14 }, (_, index) => {
        const paid = northwind(params.orgId)
          ? [2, 3, 1, 4, 2, 0, 0, 3, 5, 2, 4, 3, 1, 2][index]
          : 0;
        return {
          date: new Date(Date.now() - (13 - index) * 86_400_000)
            .toISOString()
            .slice(0, 10),
          paid,
          volume: usdc(paid * 870),
          completed: paid,
          onTime: paid > 0 ? paid - 1 : 0,
          interventions: paid > 3 ? 1 : 0,
          feesWei: String(paid * 130_000_000_000_000),
        };
      });
      return {
        metrics: northwind(params.orgId)
          ? {
              paymentsCount: 32,
              onTimeRate: 0.969,
              medianApprovalMinutes: 47,
              aiPlanRate: 0.84,
              exceptions: 2,
              unknownOperations: 1,
              completionRate: 0.941,
              interventionsPerRequest: 0.25,
              txCount: 41,
              fees: {
                totalWei: '5400000000000000',
                byStepType: {
                  APPROVE: '1200000000000000',
                  PAY: '4200000000000000',
                },
              },
              series,
              latencyByPhase: {},
              rejectionsByReason: {},
              revertsBySelector: {},
            }
          : {
              paymentsCount: 0,
              onTimeRate: 0,
              medianApprovalMinutes: 0,
              aiPlanRate: 0,
              exceptions: 0,
              unknownOperations: 0,
              completionRate: 0,
              interventionsPerRequest: 0,
              txCount: 0,
              fees: { totalWei: '0', byStepType: {} },
              series,
              latencyByPhase: {},
              rejectionsByReason: {},
              revertsBySelector: {},
            },
      };
    },
  ),

  route('get', '/orgs/:orgId/metrics/savings', ({ params }): SavingsMetrics => {
    requireOrg(params.orgId);
    const rows = northwind(params.orgId)
      ? [
          ['req_220', 'OT-2026-220', 'Orbit Telecom', usdc(310), usdc(303, 80)],
          [
            'req_041',
            'AC-2026-096',
            'Acurast Cloud',
            usdc(1410),
            usdc(1381, 80),
          ],
          [
            'req_038',
            'MS-2026-021',
            'Meridian Security',
            usdc(1800),
            usdc(1764),
          ],
          [
            'req_055',
            'MS-2026-029',
            'Meridian Security',
            usdc(1200),
            usdc(1200),
          ],
        ]
      : [];
    const perRequest = rows.map(
      ([requestId, invoiceNumber, vendorName, baseline, actual]) => ({
        requestId,
        invoiceNumber,
        vendorName,
        baseline,
        actual,
        saved: (BigInt(baseline) - BigInt(actual)).toString(),
      }),
    );
    const total = (key: 'baseline' | 'actual' | 'saved') =>
      perRequest.reduce((sum, row) => sum + BigInt(row[key]), 0n).toString();
    return {
      totals: {
        baseline: total('baseline'),
        actual: total('actual'),
        saved: total('saved'),
      },
      perRequest,
      skipped: 0,
      warnings: [],
      methodology:
        'Baseline B1 re-runs the earliest-deadline-first scheduler on the same requests under the mandate version that was Active when each batch was scheduled (PAY and REFILL caps, payee cooling and activation, amounts already paid that day). No balances are persisted, so liquidity is assumed ample and B1 is an upper bound. Value is the early-payment discount captured, minus early-payment gas (FEE-2, PAY operations only), minus late fees. Savings = B1 cost - actual cost; negative savings are reported as negative. Requests that could not be compared are counted in skipped.',
    };
  }),

  /* ───────────── Notifications ───────────── */

  route('get', '/orgs/:orgId/notifications', ({ params, query }) => {
    requireOrg(params.orgId);
    const items = northwind(params.orgId) ? db.notifications : [];
    return {
      items:
        query.get('unread') === 'true'
          ? items.filter((item) => !item.read)
          : items,
    };
  }),

  route('post', '/orgs/:orgId/notifications/:id/read', ({ params }) => {
    requireOrg(params.orgId);
    if (params.id === 'all')
      db.notifications.forEach((item) => (item.read = true));
    else
      find(
        db.notifications,
        (item) => item.id === params.id,
        'Notification',
      ).read = true;
  }),

  /* ───────────── Copilot ───────────── */

  route('post', '/orgs/:orgId/copilot/threads', ({ params }) => {
    requireOrg(params.orgId);
    const threadId = `thr_${Date.now().toString(36)}`;
    db.copilot[threadId] = [];
    return { threadId };
  }),

  route<{ text?: string; treasuryId?: string }>(
    'post',
    '/orgs/:orgId/copilot/threads/:id/messages',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const thread = db.copilot[params.id];
      if (!thread) fail(404, 'NOT_FOUND', 'Thread was not found.');
      const text = body.text?.trim();
      if (!text) fail(422, 'VALIDATION', 'Type a question.');
      if (/budget exceeded/i.test(text))
        fail(
          429,
          'AI_BUDGET_EXCEEDED',
          'The AI budget for today is used up. Data pages still work.',
        );
      thread.push({
        id: `msg_${thread.length}`,
        role: 'user',
        content: text,
        citations: [],
      });
      const reply: CopilotMessage = {
        id: `msg_${thread.length}`,
        role: 'assistant',
        ...answer(text, body.treasuryId ?? ''),
      };
      thread.push(reply);
      return { messageId: reply.id, message: reply };
    },
  ),

  route('get', '/orgs/:orgId/copilot/threads/:id', ({ params }) => {
    requireOrg(params.orgId);
    return { messages: db.copilot[params.id] ?? [] };
  }),
];

/* ───────────── Live events (SSE) ───────────── */

// MSW can only mock a stream where EventSource exists; elsewhere (jsdom) the
// client falls back to polling.
if (typeof EventSource !== 'undefined') {
  operationHandlers.push(
    sse<{ message: ServerEvent }>('*/v1/orgs/:orgId/events', ({ client }) => {
      const listener = (event: ServerEvent) => {
        client.send({ id: event.id, data: event });
      };
      db.listeners.add(listener);
      // Advance scheduled work while someone is watching.
      const timer = setInterval(tick, 500);
      setTimeout(() => {
        clearInterval(timer);
        db.listeners.delete(listener);
      }, 10 * 60_000);
    }),
  );
}
