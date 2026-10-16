/**
 * Handlers for the recordable demo scenario (docs/demo). They sit in front of the default
 * handlers only when `demoScenarioEnabled()`; the Northwind/Linh dataset stays the default.
 *
 * The scenario engine owns the state. These handlers expose it to the normal hooks:
 * `/demo/*` for the demo screens, and the seeded org/treasury/members in `db` so the shell
 * (`/me`, `/orgs/:org`, treasuries, notifications) works for Northstar API as usual.
 */
import type { MockTreasuryState } from '@/mocks/db';
import { ADDR, CHAINS, db, setSession } from '@/mocks/db';
import type { Member, User } from '@/lib/api/types';

import {
  ActionError,
  allocation,
  approveInvoice,
  economics,
  fixture,
  fundingPlan,
  ledgerStage,
  o1Breakdown,
  outcomeLines,
  pauseAgent,
  submitInvoice,
  submitSecurityInvoice,
  supplyPlan,
  tBreakdown,
  total,
  uploadInvoice,
  OUTCOME_FOOTER,
  type ActionResult,
  type DemoRole,
  type DirectorAction,
  type ScenarioState,
} from '../scenario/engine';
import {
  dispatchEvents,
  getScenario,
  isFollower,
  runDirector,
  setRole,
  startScenario,
  subscribeScenario,
} from '../scenario/store';
import { fail, route } from './core';

export const DEMO_ORG_ID = 'org-northstar';
export const DEMO_TREASURY_ID = 'trs-northstar';

const USERS: Record<DemoRole, User & { roles: Member['roles'] }> = {
  FINANCE: {
    id: 'usr_ns_linh',
    email: 'linh@northstar.test',
    name: 'Linh',
    roles: ['FIN'],
  },
  APPROVER: {
    id: 'usr_ns_an',
    email: 'an@northstar.test',
    name: 'An',
    roles: ['APR'],
  },
  OWNER: {
    id: 'usr_ns_minh',
    email: 'minh@northstar.test',
    name: 'Minh',
    roles: ['OWN'],
  },
};

/** bigint is not JSON: every amount leaves the mock API as a decimal string. */
function serialize(value: unknown): unknown {
  if (typeof value === 'bigint') return value.toString();
  if (Array.isArray(value)) return value.map(serialize);
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [key, serialize(item)]),
    );
  }
  return value;
}

export function scenarioView(state: ScenarioState = getScenario()) {
  const ledger = state.ledger;
  const cash = BigInt(ledger.t) + BigInt(ledger.o1) + BigInt(ledger.o2);
  const supply = supplyPlan(state);
  return serialize({
    state,
    stage: ledgerStage(state),
    follower: isFollower(),
    t: tBreakdown(state),
    o1: o1Breakdown(state),
    cash,
    aave: BigInt(ledger.aave),
    total: total(ledger),
    funding: fundingPlan(),
    economics: economics(),
    allocation: allocation(state),
    supplyPlan: supply,
    outcome: {
      lines: state.supply.status === 'CONFIRMED' ? outcomeLines(state) : [],
      footer: OUTCOME_FOOTER,
    },
    fixture,
  });
}

function mapError(error: unknown): never {
  if (error instanceof ActionError) {
    return fail(error.status, error.code, error.message);
  }
  throw error;
}

function perform(build: (state: ScenarioState) => ActionResult) {
  try {
    const result = build(getScenario());
    if (result.events.length > 0) dispatchEvents(result.events);
    return {
      noop: Boolean(result.noop),
      message: result.message ?? null,
      ...(scenarioView() as object),
    };
  } catch (error) {
    return mapError(error);
  }
}

/* ───────────── The Northstar org inside the shared mock db ───────────── */

function treasuryStateFor(state: ScenarioState): MockTreasuryState {
  const t = tBreakdown(state);
  const alloc = allocation(state);
  const owners = [ADDR.me];
  const holds = t.fundingHoldA + o1Breakdown(state).executionHold;
  return {
    treasury: {
      id: DEMO_TREASURY_ID,
      name: 'Northstar treasury',
      chainId: CHAINS[0].chainId,
      chainName: 'Simulation',
      asset: CHAINS[0].assets[0],
      moduleAddress: ADDR.module,
      status: 'Active',
    },
    wallets: [
      {
        role: 'T',
        label: 'T / Treasury',
        safeAddress: ADDR.safeT,
        balance: state.ledger.t,
        buffer: fixture.accounts[0].buffer,
        target: fixture.accounts[0].buffer,
        threshold: 1,
        owners,
      },
      {
        role: 'O1',
        label: 'O1 / Vendor payments',
        safeAddress: ADDR.safeO1,
        balance: state.ledger.o1,
        buffer: fixture.accounts[1].buffer,
        target: fixture.accounts[1].target,
        threshold: 1,
        owners,
      },
      {
        role: 'O2',
        label: 'O2 / Payroll',
        safeAddress: ADDR.safeO2,
        balance: state.ledger.o2,
        buffer: fixture.accounts[2].buffer,
        target: fixture.accounts[2].target,
        threshold: 1,
        owners,
      },
    ],
    coverage: {
      status: 'COMPLETE',
      acknowledged: false,
      missing: [],
      snapshotBlock: null,
      details: [],
    },
    mandate: {
      version: fixture.mandate.version,
      status: 'Active',
      expiresAt: fixture.mandate.expiresAt,
    },
    budgets: [
      {
        action: 'PAY',
        usedToday: state.ledger.vendorPaid,
        dailyLimit: fixture.mandate.payDaily,
        perRequest: fixture.mandate.payPerTx,
      },
      {
        action: 'REFILL',
        usedToday: '0',
        dailyLimit: fixture.mandate.refillDaily,
        perRequest: fixture.mandate.refillPerTx,
      },
    ],
    staleness: { blockNumber: 0, observedAt: state.clock, stale: false },
    position: {
      safeUsdc: (
        BigInt(state.ledger.t) +
        BigInt(state.ledger.o1) +
        BigInt(state.ledger.o2)
      ).toString(),
      aUsdc: state.ledger.aave,
      poolLiquidity: fixture.pool.availableToWithdraw,
      requiredReserve: {
        paymentReserve: alloc.payroll.toString(),
        floor: alloc.floor.toString(),
        holds: holds.toString(),
        total: (alloc.protectedTotal + holds).toString(),
      },
      availableForSupply: alloc.surplus.toString(),
      supplyApyBps: 0,
      lastAction: {
        kind: 'NONE',
        amount: '0',
        at: state.clock,
        explanation: 'Synthetic scenario. No yield is realized or promised.',
      },
    },
    queues: { approvals: 0, governance: 0, review: 0, reconciliation: 0 },
    activity: state.activity.map((entry) => ({
      id: entry.id,
      at: entry.at,
      actor: 'agent' as const,
      text: entry.text,
    })),
  };
}

function syncDb(state: ScenarioState) {
  db.treasuries[DEMO_TREASURY_ID] = treasuryStateFor(state);
  const user = USERS[state.role];
  if (db.session?.id !== user.id) {
    setSession({ id: user.id, email: user.email, name: user.name });
  }
}

let installed = false;

/** Registers Northstar API next to the default org and keeps its treasury in step with the scenario. */
export function installDemoScenario() {
  if (installed) return;
  installed = true;
  db.orgs.push({
    id: DEMO_ORG_ID,
    name: fixture.organization.name,
    country: 'VN',
    displayTz: 'UTC',
    soloMode: false,
    autoMatch: false,
    treasuries: [{ id: DEMO_TREASURY_ID, name: 'Northstar treasury' }],
  });
  db.orgMembers[DEMO_ORG_ID] = (Object.keys(USERS) as DemoRole[]).map(
    (role) => ({
      userId: USERS[role].id,
      name: USERS[role].name,
      email: USERS[role].email,
      roles: USERS[role].roles,
      status: 'Active' as const,
    }),
  );
  db.moduleEnabled[DEMO_TREASURY_ID] = ['T', 'O1', 'O2'];
  db.mandates[DEMO_TREASURY_ID] = [];
  db.notifications = [];
  startScenario();
  syncDb(getScenario());
  subscribeScenario(syncDb);
}

/* ───────────── Routes ───────────── */

const open = { public: true } as const;

export const demoHandlers = [
  route('get', '/demo/scenario', () => scenarioView(), open),

  route<{ role?: DemoRole }>(
    'post',
    '/demo/role',
    ({ body }) => {
      if (!body.role || !(body.role in USERS)) {
        fail(422, 'DEMO_ROLE_INVALID', 'Pick Linh, An or Minh.');
      }
      // A role switch never resets the scenario.
      setRole(body.role);
      return scenarioView();
    },
    open,
  ),

  route<{ fileName?: string }>(
    'post',
    '/demo/invoices/upload',
    ({ body }) => perform((state) => uploadInvoice(state, body.fileName ?? '')),
    open,
  ),

  route<{ verified?: boolean }>(
    'post',
    '/demo/invoices/inv-cloud-042/submit',
    ({ body }) =>
      perform((state) => submitInvoice(state, Boolean(body.verified))),
    open,
  ),

  route(
    'post',
    '/demo/invoices/inv-cloud-042/approve',
    () => perform(approveInvoice),
    open,
  ),

  route(
    'post',
    '/demo/invoices/inv-security-043/submit',
    () => perform(submitSecurityInvoice),
    open,
  ),

  route('post', '/demo/agent/pause', () => perform(pauseAgent), open),

  route(
    'post',
    '/demo/director/:action',
    async ({ params }) => {
      try {
        const result = await runDirector(params.action as DirectorAction);
        return { ...result, ...(scenarioView() as object) };
      } catch (error) {
        return mapError(error);
      }
    },
    open,
  ),
];
