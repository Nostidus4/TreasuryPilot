import { useState } from 'react';
import {
  ArrowDownLeft,
  ArrowUpRight,
  Check,
  ChevronDown,
  LockKeyhole,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

import {
  ActionButton,
  Badge,
  Card,
  CardTitle,
  MockAppShell,
  PageHeading,
  SectionLabel,
} from '@/components/mock';

export function MockPaymentPlanPage() {
  const [refreshed, setRefreshed] = useState(false);
  const [showChecks, setShowChecks] = useState(true);

  return (
    <MockAppShell activePage="plans">
      <PageHeading
        eyebrow="Acme Finance / Treasury operations"
        title="AI payment plan"
        description="A fictional step-by-step plan with fixture inputs, policy decisions, and a separate read-only explanation."
      >
        <Badge tone="blue">
          <Sparkles aria-hidden="true" size={12} /> Optimizer · validated
        </Badge>
        <ActionButton variant="secondary" onClick={() => setRefreshed(true)}>
          <RefreshCw aria-hidden="true" size={14} />
          {refreshed ? 'Simulation refreshed' : 'Run read-only simulation'}
        </ActionButton>
      </PageHeading>

      {refreshed && (
        <div
          role="status"
          className="mb-4 rounded-xl border border-emerald-100 bg-emerald-50/80 px-4 py-3 text-xs text-emerald-900"
        >
          Simulation recalculated from the same fictional fixture. No
          transaction was created or submitted.
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,0.8fr)]">
        <div className="flex flex-col gap-4">
          <Card>
            <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-sm font-bold">
                    Plan PL-482 · Acurast Cloud
                  </h2>
                  <Badge tone="green">Policy: ALLOW</Badge>
                </div>
                <p className="mt-1 text-[11px] text-slate-400">
                  Invoice AC-2026-104 · due Oct 12, 2026 · USDC TEST
                </p>
              </div>
              <Badge tone="slate">Preview only</Badge>
            </div>
            <div className="grid gap-4 rounded-xl bg-slate-50/80 p-4 sm:grid-cols-[1fr_auto] sm:items-end">
              <div>
                <SectionLabel>Authorized supplier payment</SectionLabel>
                <p className="mt-2 text-[29px] font-bold leading-none tracking-[-0.05em]">
                  1,450{' '}
                  <span className="text-sm font-semibold tracking-normal text-slate-500">
                    USDC TEST
                  </span>
                </p>
                <p className="mt-2 text-[10px] text-slate-500">
                  Exact invoice amount · 0x41a8…92e1 · allowlisted
                </p>
              </div>
              <div className="sm:text-right">
                <SectionLabel>Approval status</SectionLabel>
                <div className="mt-2 inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
                  <ShieldCheck aria-hidden="true" size={15} /> Human approval in
                  fixture
                </div>
                <p className="mt-1 text-[10px] text-slate-400">
                  PaymentAuthorization · fictional demo state
                </p>
              </div>
            </div>

            <div className="my-5 grid gap-3 sm:grid-cols-2">
              <PlanStep
                number="01"
                action="REFILL"
                route="Treasury Safe T → Operating O1"
                amount="850"
                detail="Internal transfer · restore the operating target"
                icon={ArrowDownLeft}
              />
              <PlanStep
                number="02"
                action="PAY"
                route="Operating O1 → Acurast Cloud"
                amount="1,450"
                detail="Approved invoice · exact recipient and amount"
                icon={ArrowUpRight}
              />
            </div>

            <div className="flex flex-col gap-3 border-t border-slate-100 pt-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-center gap-2 text-[11px] text-slate-500">
                <ShieldCheck
                  aria-hidden="true"
                  size={15}
                  className="text-emerald-600"
                />{' '}
                Reserve maintained <span className="text-slate-300">·</span>{' '}
                within per-payment cap <span className="text-slate-300">·</span>{' '}
                allowlisted payee
              </div>
              <ActionButton
                variant="quiet"
                onClick={() => setShowChecks((current) => !current)}
                aria-expanded={showChecks}
              >
                Inspect validator checks{' '}
                <ChevronDown
                  aria-hidden="true"
                  className={`transition ${showChecks ? 'rotate-180' : ''}`}
                  size={14}
                />
              </ActionButton>
            </div>
            {showChecks && (
              <div className="mt-3 grid gap-2 rounded-xl border border-emerald-100 bg-emerald-50/50 p-3 sm:grid-cols-2">
                <CheckLine label="Fixture treasury and Aave snapshot loaded" />
                <CheckLine label="Demo authorization is within its time window" />
                <CheckLine label="USDC TEST and Sepolia TEST match mandate" />
                <CheckLine label="Required Safe reserve remains protected" />
              </div>
            )}
          </Card>

          <Card>
            <CardTitle
              title="Execution sequence"
              detail="Re-read and reconcile after every confirmed step; unknown transaction status stops the sequence."
              action={<Badge tone="blue">Awaiting preview</Badge>}
            />
            <ol className="relative ml-2 border-l border-blue-100 pl-6">
              <TimelineStep
                state="done"
                title="Plan validated against current snapshot"
                detail="Fixture policy result · sample block 6,812,904"
              />
              <TimelineStep
                state="current"
                title="REFILL T → O1"
                detail="850 USDC TEST · ready in this demo sequence"
              />
              <TimelineStep
                state="pending"
                title="Re-read Safe and operating balances"
                detail="Only after REFILL confirmation"
              />
              <TimelineStep
                state="pending"
                title="PAY Acurast Cloud"
                detail="1,450 USDC TEST · exact signed payment option"
              />
              <TimelineStep
                state="pending"
                title="Reconcile final balances and audit evidence"
                detail="After payment confirmation"
                last
              />
            </ol>
            <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-3 text-[10px] leading-5 text-slate-500">
              This page is a static product preview. It does not connect to a
              wallet, sign EIP-712 data, or broadcast a transaction.
            </p>
          </Card>
        </div>

        <div className="flex flex-col gap-4">
          <Card>
            <CardTitle
              title="Why this plan?"
              detail="AI explanation is advisory; real execution requires verified inputs and policy rules."
            />
            <div className="rounded-xl border border-blue-100 bg-blue-50/70 p-4">
              <div className="flex items-center gap-2 text-xs font-bold text-blue-800">
                <Sparkles aria-hidden="true" size={15} /> Read-only AI
                explanation
              </div>
              <p className="mt-2.5 text-xs leading-6 text-blue-950/80">
                Operating O1 has 1,100 USDC TEST available. The approved invoice
                is 1,450 USDC TEST, and the 500 USDC TEST target should remain
                after payment. A refill of 850 USDC TEST covers both the payment
                shortfall and the target.
              </p>
              <p className="mt-3 text-[10px] text-blue-700/70">
                Fixture sources: wallet snapshot · approved invoice · sample
                mandate
              </p>
            </div>
            <div className="mt-4 divide-y divide-slate-100">
              <KeyValue label="Due date" value="Oct 12, 2026" />
              <KeyValue
                label="Operating target after payment"
                value="500 USDC TEST"
              />
              <KeyValue
                label="Daily paid + planned"
                value="5,100 / 10,000 USDC TEST"
              />
              <KeyValue label="Payee status" value="Active allowlist" />
            </div>
          </Card>

          <Card>
            <CardTitle
              title="Policy decisions"
              detail="Deterministic checks evaluate this exact plan."
              action={<Badge tone="green">ALLOW</Badge>}
            />
            <div className="space-y-3">
              <PolicyRow
                title="Payment per-transaction cap"
                value="ALLOW"
                detail="1,450 ≤ 2,000 USDC TEST"
              />
              <PolicyRow
                title="Daily autonomous payment cap"
                value="ALLOW"
                detail="5,100 ≤ 10,000 USDC TEST"
              />
              <PolicyRow
                title="Payee allowlist and cooling"
                value="ALLOW"
                detail="Verified vendor address"
              />
              <PolicyRow
                title="Required reserve after refill"
                value="ALLOW"
                detail="Safe remains above 23,440 USDC TEST"
              />
              <PolicyRow
                title="Authorization / replay check"
                value="ALLOW"
                detail="Fixture authorization · unused · mandate v3"
              />
            </div>
          </Card>

          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3.5 text-[11px] leading-5 text-amber-900">
            <span className="font-semibold">Execution boundary.</span> AI does
            not approve payments or grant authority. A valid human signature,
            the policy engine, and on-chain mandate checks are all required.
          </div>
        </div>
      </div>
    </MockAppShell>
  );
}

function PlanStep({
  number,
  action,
  route,
  amount,
  detail,
  icon: Icon,
}: {
  number: string;
  action: string;
  route: string;
  amount: string;
  detail: string;
  icon: typeof ArrowDownLeft;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 transition hover:border-blue-200 hover:shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-blue-50 text-blue-700">
            <Icon aria-hidden="true" size={16} />
          </span>
          <span className="text-[10px] font-bold uppercase tracking-[0.08em] text-slate-400">
            Step {number}
          </span>
          <Badge tone="blue">{action}</Badge>
        </div>
        <LockKeyhole aria-hidden="true" size={14} className="text-slate-300" />
      </div>
      <p className="mt-3 text-xs font-semibold text-slate-800">{route}</p>
      <p className="mt-1 text-[10px] leading-4 text-slate-400">{detail}</p>
      <p className="mt-3 text-lg font-bold tracking-tight">
        {amount}{' '}
        <span className="text-[10px] font-medium text-slate-400">
          USDC TEST
        </span>
      </p>
    </div>
  );
}

function CheckLine({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[10px] font-medium text-emerald-900">
      <Check
        aria-hidden="true"
        size={13}
        className="shrink-0 text-emerald-600"
      />
      {label}
    </span>
  );
}

function TimelineStep({
  state,
  title,
  detail,
  last = false,
}: {
  state: 'done' | 'current' | 'pending';
  title: string;
  detail: string;
  last?: boolean;
}) {
  return (
    <li className={`relative pb-5 last:pb-0 ${last ? 'pb-0' : ''}`}>
      <span
        className={`absolute -left-[31px] top-0.5 grid h-4 w-4 place-items-center rounded-full border-2 border-white ring-1 ${state === 'done' ? 'bg-emerald-500 ring-emerald-200' : state === 'current' ? 'bg-blue-600 ring-blue-200' : 'bg-white ring-slate-200'}`}
      >
        {state === 'done' && (
          <Check aria-hidden="true" size={9} className="text-white" />
        )}
        {state === 'current' && (
          <span className="h-1.5 w-1.5 rounded-full bg-white" />
        )}
      </span>
      <div className="flex flex-wrap items-center gap-2">
        <p
          className={`text-xs font-semibold ${state === 'pending' ? 'text-slate-400' : 'text-slate-800'}`}
        >
          {title}
        </p>
        {state === 'current' && <Badge tone="blue">Next</Badge>}
      </div>
      <p className="mt-1 text-[10px] leading-4 text-slate-400">{detail}</p>
    </li>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 py-3 first:pt-0 last:pb-0">
      <span className="text-[10px] text-slate-500">{label}</span>
      <span className="text-right text-[10px] font-semibold text-slate-800">
        {value}
      </span>
    </div>
  );
}

function PolicyRow({
  title,
  value,
  detail,
}: {
  title: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-semibold text-slate-700">{title}</p>
        <p className="mt-0.5 text-[10px] text-slate-400">{detail}</p>
      </div>
      <Badge tone="green">{value}</Badge>
    </div>
  );
}
