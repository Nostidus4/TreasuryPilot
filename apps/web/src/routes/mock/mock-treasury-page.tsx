import { useState } from 'react';
import {
  ArrowDownLeft,
  ArrowLeftRight,
  Check,
  Clock3,
  Info,
  Landmark,
  ShieldCheck,
  WalletCards,
  Zap,
} from 'lucide-react';

import {
  ActionButton,
  Badge,
  Card,
  CardTitle,
  MiniChart,
  MockAppShell,
  PageHeading,
  SectionLabel,
} from '@/components/mock';

export function MockTreasuryPage() {
  const [horizon, setHorizon] = useState<'7 days' | '30 days'>('7 days');
  const [showFormula, setShowFormula] = useState(false);

  return (
    <MockAppShell activePage="treasury">
      <PageHeading
        eyebrow="Acme Finance / Treasury operations"
        title="Treasury & liquidity"
        description="Wallet balances, approved-payment reserves, withdrawable Aave liquidity, and permitted routes."
      >
        <Badge tone="green">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" /> Snapshot
          fixture · sample block 6,812,904
        </Badge>
        <ActionButton
          variant="secondary"
          onClick={() => setShowFormula((current) => !current)}
          aria-expanded={showFormula}
        >
          <Info aria-hidden="true" size={14} />
          {showFormula ? 'Hide reserve formula' : 'Reserve formula'}
        </ActionButton>
      </PageHeading>

      <div className="mb-4 grid gap-3 md:grid-cols-3">
        <WalletCard
          icon={Landmark}
          name="Treasury Safe · T"
          address="0x74a8…b162"
          balance="125,000"
          descriptor="Primary reserve · USDC TEST"
          tone="blue"
        />
        <WalletCard
          icon={WalletCards}
          name="Operating wallet · O1"
          address="0x329f…a941"
          balance="1,100"
          descriptor="Approved supplier payments · USDC TEST"
          tone="violet"
        />
        <WalletCard
          icon={WalletCards}
          name="Aave V3 position"
          address="Sepolia TEST market"
          balance="38,000"
          descriptor="Supplied USDC TEST · 4.20% demo APY"
          tone="green"
        />
      </div>

      {showFormula && (
        <div className="mb-4 rounded-xl border border-blue-100 bg-blue-50/70 p-4 text-xs leading-6 text-blue-950">
          <p className="font-bold">
            Required Safe reserve = payment reserve + operating buffer + debt
            service reserve + execution holds
          </p>
          <p className="mt-1">
            Available for supply = max(0, Safe USDC TEST − required Safe
            reserve). Payment reserves are never supplied. Accessible liquidity
            includes Safe USDC TEST plus Aave USDC TEST that is immediately
            withdrawable.
          </p>
        </div>
      )}

      <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.75fr)]">
        <Card>
          <CardTitle
            title="Reserve coverage"
            detail="Available supply capacity is calculated from this fictional fixture."
            action={<Badge tone="green">Coverage complete</Badge>}
          />
          <div className="grid gap-5 sm:grid-cols-[1fr_auto] sm:items-end">
            <div>
              <SectionLabel>Treasury Safe balance</SectionLabel>
              <p className="mt-2 text-[31px] font-bold leading-none tracking-[-0.05em]">
                125,000{' '}
                <span className="text-sm font-semibold tracking-normal text-slate-500">
                  USDC TEST
                </span>
              </p>
              <p className="mt-2 text-[10px] text-slate-400">
                Sepolia TEST · Safe T
              </p>
            </div>
            <div className="rounded-xl bg-emerald-50 px-3.5 py-2.5 text-right">
              <p className="text-[10px] text-emerald-700">
                Available for supply
              </p>
              <p className="mt-1 text-sm font-bold text-emerald-900">
                101,560 USDC TEST
              </p>
            </div>
          </div>
          <div className="mt-5 rounded-xl bg-slate-50 p-4">
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="text-[11px] font-semibold text-slate-700">
                Required Safe reserve
              </span>
              <span className="text-xs font-bold">23,440 USDC TEST</span>
            </div>
            <div className="h-2 overflow-hidden rounded-full bg-white">
              <div className="h-full w-[18.8%] rounded-full bg-gradient-to-r from-blue-600 to-indigo-400" />
            </div>
            <div className="mt-2 flex justify-between gap-3 text-[10px] text-slate-400">
              <span>Payment obligations protected</span>
              <span>101,560 above reserve</span>
            </div>
          </div>
          <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <ReserveItem label="Payment reserve" amount="3,440" />
            <ReserveItem label="Operating buffer" amount="20,000" />
            <ReserveItem label="Debt service" amount="0" />
            <ReserveItem label="Execution holds" amount="0" />
          </div>
        </Card>

        <Card className="h-fit">
          <CardTitle
            title="Accessible liquidity"
            detail="Safe balance plus immediately withdrawable Aave USDC TEST"
          />
          <div className="rounded-2xl bg-gradient-to-br from-[#467ff0] via-[#2866db] to-[#2550b0] p-4 text-white">
            <SectionLabel>Accessible now</SectionLabel>
            <p className="mt-2 text-[27px] font-bold tracking-[-0.04em]">
              163,000 <span className="text-sm font-semibold">USDC TEST</span>
            </p>
            <div className="mt-4 flex items-center justify-between text-[10px] text-blue-100">
              <span>Safe 125,000 + Aave 38,000</span>
              <Landmark aria-hidden="true" size={15} />
            </div>
          </div>
          <div className="mt-4 space-y-3">
            <LiquidityRow
              label="Aave supplied underlying"
              value="38,000 USDC TEST"
              detail="Available to withdraw: 38,000"
            />
            <LiquidityRow
              label="Aave pool liquidity"
              value="42,600 USDC TEST"
              detail="Pool capacity exceeds position"
            />
            <LiquidityRow
              label="Estimated supply APY"
              value="4.20%"
              detail="Test market display value"
            />
          </div>
          <p className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5 text-[10px] leading-5 text-slate-500">
            Yield is a secondary objective. Supply is limited to funds above the
            full required reserve; no yield is guaranteed.
          </p>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(320px,0.75fr)]">
        <Card>
          <CardTitle
            title="Liquidity forecast"
            detail={`Projected position and reserve coverage for the next ${horizon.toLowerCase()}.`}
            action={
              <div
                className="flex rounded-lg bg-slate-100 p-0.5"
                role="group"
                aria-label="Forecast horizon"
              >
                {(['7 days', '30 days'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={horizon === value}
                    onClick={() => setHorizon(value)}
                    className={`rounded-md px-2.5 py-1.5 text-[10px] font-semibold ${horizon === value ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500'}`}
                  >
                    {value}
                  </button>
                ))}
              </div>
            }
          />
          <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-blue-600" /> Accessible
              liquidity
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-orange-400" /> Projected
              outflows
            </span>
            <span className="ml-auto text-slate-400">
              {horizon === '7 days' ? 'Oct 11–18' : 'Oct 11–Nov 10'}
            </span>
          </div>
          <MiniChart variant="forecast" range={horizon} />
          <div className="mt-3 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3.5 text-[11px] leading-5 text-emerald-900">
            No reserve breach projected for approved obligations in this
            fixture. Forecasts depend on confirmed transactions and current pool
            liquidity.
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <Card>
            <CardTitle
              title="Permitted routes"
              detail="Internal transfers and lending actions under the active mandate"
            />
            <RouteRow
              title="Treasury T → Operating O1"
              detail="REFILL for a valid approved payment"
              state="Allowed"
              tone="green"
              icon={ArrowLeftRight}
            />
            <RouteRow
              title="Treasury T ↔ Aave V3"
              detail="SUPPLY above reserve · WITHDRAW for obligations"
              state="Allowed"
              tone="green"
              icon={ArrowDownLeft}
            />
            <RouteRow
              title="BORROW / REPAY"
              detail="Requires a separate owner approval for the exact plan"
              state="Owner approval"
              tone="amber"
              icon={ShieldCheck}
            />
            <p className="mt-4 rounded-xl border border-blue-100 bg-blue-50/70 p-3 text-[10px] leading-5 text-blue-900">
              A refill must be tied to an approved obligation and preserve the
              Safe reserve. Unknown routes and assets are blocked.
            </p>
          </Card>
          <Card>
            <CardTitle
              title="Network readiness"
              detail="Test environment status"
            />
            <div className="space-y-3">
              <NetworkLine
                icon={Zap}
                label="O1 native gas"
                value="0.42 ETH TEST"
              />
              <NetworkLine
                icon={Zap}
                label="Aave market"
                value="Available · Sepolia TEST"
              />
              <NetworkLine
                icon={Clock3}
                label="Snapshot age"
                value="2 minutes"
              />
            </div>
            <div className="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-[10px] font-semibold text-emerald-800">
              <Check aria-hidden="true" size={13} /> No gas shortage detected
            </div>
          </Card>
        </div>
      </div>
    </MockAppShell>
  );
}

function WalletCard({
  icon: Icon,
  name,
  address,
  balance,
  descriptor,
  tone,
}: {
  icon: typeof Landmark;
  name: string;
  address: string;
  balance: string;
  descriptor: string;
  tone: 'blue' | 'violet' | 'green';
}) {
  const color = {
    blue: 'bg-blue-50 text-blue-700',
    violet: 'bg-violet-50 text-violet-700',
    green: 'bg-emerald-50 text-emerald-700',
  };
  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between gap-2">
        <span
          className={`grid h-9 w-9 place-items-center rounded-xl ${color[tone]}`}
        >
          <Icon aria-hidden="true" size={17} />
        </span>
        <Badge tone="blue">Snapshot</Badge>
      </div>
      <p className="mt-4 text-xs font-semibold text-slate-600">{name}</p>
      <p className="mt-1 text-[10px] text-slate-400">{address}</p>
      <p className="mt-3 text-[26px] font-bold leading-none tracking-[-0.04em]">
        {balance}
        <span className="ml-1.5 text-[10px] font-semibold tracking-normal text-slate-400">
          USDC TEST
        </span>
      </p>
      <p className="mt-2 text-[10px] text-slate-400">{descriptor}</p>
    </Card>
  );
}

function ReserveItem({ label, amount }: { label: string; amount: string }) {
  return (
    <div className="rounded-lg border border-slate-200/80 bg-white px-2.5 py-2">
      <p className="truncate text-[9px] text-slate-400">{label}</p>
      <p className="mt-1 text-xs font-bold text-slate-800">
        {amount}{' '}
        <span className="text-[9px] font-medium text-slate-400">USDC TEST</span>
      </p>
    </div>
  );
}

function LiquidityRow({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-slate-100 pb-3 last:border-0 last:pb-0">
      <div>
        <p className="text-[10px] font-semibold text-slate-700">{label}</p>
        <p className="mt-1 text-[9px] text-slate-400">{detail}</p>
      </div>
      <span className="whitespace-nowrap text-[10px] font-semibold text-slate-800">
        {value}
      </span>
    </div>
  );
}

function RouteRow({
  title,
  detail,
  state,
  tone,
  icon: Icon,
}: {
  title: string;
  detail: string;
  state: string;
  tone: 'green' | 'amber';
  icon: typeof ArrowDownLeft;
}) {
  return (
    <div className="flex gap-3 border-b border-slate-100 py-3 first:pt-0 last:border-0 last:pb-0">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-blue-50 text-blue-700">
        <Icon aria-hidden="true" size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-[10px] font-semibold text-slate-800">{title}</p>
          <Badge tone={tone}>{state}</Badge>
        </div>
        <p className="mt-1 text-[9px] leading-4 text-slate-400">{detail}</p>
      </div>
    </div>
  );
}

function NetworkLine({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-2.5">
      <Icon aria-hidden="true" size={14} className="text-slate-400" />
      <span className="flex-1 text-[10px] text-slate-500">{label}</span>
      <span className="text-[10px] font-semibold text-slate-700">{value}</span>
    </div>
  );
}
