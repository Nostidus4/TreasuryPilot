import { NavLink } from 'react-router-dom';
import {
  ArrowDownLeft,
  ArrowRight,
  ArrowUpRight,
  CalendarDays,
  CircleCheck,
  Clock3,
  FileCheck2,
  Landmark,
  ShieldCheck,
  Sparkles,
  WalletCards,
} from 'lucide-react';

import {
  Badge,
  Card,
  CardTitle,
  InlineLink,
  MiniChart,
  MockAppShell,
  PageHeading,
  SectionLabel,
  StatCard,
} from '@/components/mock';
import { mockInvoices, money, statusTone } from '@/lib/mock-data';

export function MockDashboardPage() {
  return (
    <MockAppShell activePage="dashboard">
      <PageHeading
        eyebrow="Acme Finance / Treasury"
        title="Good morning, Avery"
        description="Your treasury command center. Here’s what needs attention today."
      >
        <Badge tone="slate">
          <CalendarDays aria-hidden="true" size={12} /> Oct 11, 2026
        </Badge>
        <NavLink
          to="/mock/invoices"
          className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-blue-600 bg-blue-600 px-3.5 py-2 text-xs font-semibold text-white shadow-sm shadow-blue-600/15 hover:bg-blue-700"
        >
          Review invoices <ArrowRight aria-hidden="true" size={14} />
        </NavLink>
      </PageHeading>

      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Treasury Safe · T"
          value="125,000"
          meta="USDC TEST · Sepolia TEST"
          icon={Landmark}
        />
        <StatCard
          label="Operating wallet · O1"
          value="1,100"
          meta="USDC TEST · 500 target after payment"
          icon={WalletCards}
          tone="green"
        />
        <StatCard
          label="Approved obligations"
          value="3,440"
          meta="USDC TEST · 2 approved requests"
          icon={FileCheck2}
          tone="amber"
        />
        <StatCard
          label="Mandate status"
          value="Active"
          meta="Version 3 · Sepolia TEST demo state"
          icon={ShieldCheck}
          tone="green"
        />
      </div>

      <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,1.65fr)_minmax(310px,0.9fr)]">
        <Card>
          <CardTitle
            title="Cash flow & available liquidity"
            detail="Fictional fixture · Treasury Safe and projected obligations"
            action={
              <Badge tone="green">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                Demo snapshot
              </Badge>
            }
          />
          <div className="mb-2 flex flex-wrap gap-x-4 gap-y-2 text-[10px] text-slate-500">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-blue-600" /> Treasury
              balance
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full bg-orange-400" /> Monthly
              outflow
            </span>
            <span className="ml-auto text-slate-400">Last 6 months</span>
          </div>
          <MiniChart />
          <div className="mt-4 grid grid-cols-3 divide-x divide-slate-100 rounded-xl bg-slate-50/80 py-3">
            <div className="px-3">
              <p className="text-[10px] text-slate-400">Accessible liquidity</p>
              <p className="mt-1 text-sm font-bold">
                163,000{' '}
                <span className="text-[10px] font-medium text-slate-400">
                  USDC TEST
                </span>
              </p>
            </div>
            <div className="px-3">
              <p className="text-[10px] text-slate-400">Required reserve</p>
              <p className="mt-1 text-sm font-bold">
                23,440{' '}
                <span className="text-[10px] font-medium text-slate-400">
                  USDC TEST
                </span>
              </p>
            </div>
            <div className="px-3">
              <p className="text-[10px] text-slate-400">Available to supply</p>
              <p className="mt-1 text-sm font-bold text-blue-700">
                101,560{' '}
                <span className="text-[10px] font-medium text-slate-400">
                  USDC TEST
                </span>
              </p>
            </div>
          </div>
        </Card>

        <div className="flex flex-col gap-4">
          <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[#467ff0] via-[#2866db] to-[#2550b0] p-5 text-white shadow-lg shadow-blue-900/10">
            <div className="absolute -right-10 -top-20 h-52 w-52 rounded-full bg-white/10 blur-2xl" />
            <div className="relative flex items-start justify-between">
              <div>
                <SectionLabel>Company treasury · Safe T</SectionLabel>
                <p className="mt-4 text-[30px] font-bold tracking-[-0.04em]">
                  125,000{' '}
                  <span className="text-sm font-semibold">USDC TEST</span>
                </p>
              </div>
              <span className="rounded-xl bg-white/15 p-2">
                <ShieldCheck aria-hidden="true" size={18} />
              </span>
            </div>
            <div className="relative mt-6 flex justify-between text-[10px] text-blue-100">
              <span>0x74a8…b162</span>
              <span>SEPOLIA · TEST</span>
            </div>
          </div>
          <Card className="flex-1">
            <CardTitle
              title="Reserve protection"
              action={<Badge tone="green">Maintained</Badge>}
            />
            <div className="flex items-end justify-between gap-3">
              <span className="text-xs text-slate-500">
                Minimum Safe reserve
              </span>
              <strong className="text-xs">23,440 USDC TEST</strong>
            </div>
            <div className="mt-2.5 h-2 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full w-[76%] rounded-full bg-gradient-to-r from-blue-600 to-sky-400" />
            </div>
            <div className="mt-2 flex justify-between gap-2 text-[10px] text-slate-400">
              <span>Safe balance above required reserve</span>
              <span className="font-semibold text-slate-600">
                101,560 USDC TEST
              </span>
            </div>
            <div className="mt-4 rounded-xl border border-emerald-100 bg-emerald-50/70 p-3 text-[11px] leading-5 text-emerald-900">
              Approved payment reserves remain in the Safe and are excluded from
              supply capacity.
            </div>
          </Card>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(310px,0.85fr)]">
        <Card className="overflow-hidden">
          <CardTitle
            title="Upcoming payment requests"
            detail="Human approved obligations and items waiting for review"
            action={<InlineLink to="/mock/invoices">View all</InlineLink>}
          />
          <div className="-mx-4 overflow-x-auto sm:-mx-5">
            <table className="w-full min-w-[600px] border-collapse text-left">
              <thead>
                <tr className="bg-slate-50 text-[10px] font-semibold text-slate-400">
                  <th className="px-4 py-3 sm:px-5">Vendor</th>
                  <th className="px-3 py-3">Invoice</th>
                  <th className="px-3 py-3">Amount</th>
                  <th className="px-3 py-3">Due date</th>
                  <th className="px-3 py-3 sm:px-5">Status</th>
                </tr>
              </thead>
              <tbody>
                {mockInvoices.slice(0, 4).map((invoice) => (
                  <tr
                    key={invoice.invoice}
                    className="border-t border-slate-100 text-xs"
                  >
                    <td className="px-4 py-3.5 font-semibold text-slate-800 sm:px-5">
                      {invoice.vendor}
                    </td>
                    <td className="px-3 py-3.5 text-slate-500">
                      {invoice.invoice}
                    </td>
                    <td className="px-3 py-3.5 font-semibold">
                      {money(invoice.amount)}{' '}
                      <span className="text-[10px] font-normal text-slate-400">
                        USDC TEST
                      </span>
                    </td>
                    <td className="px-3 py-3.5 text-slate-500">
                      {invoice.due}
                    </td>
                    <td className="px-3 py-3.5 sm:px-5">
                      <Badge tone={statusTone(invoice.status)}>
                        {invoice.status}
                      </Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card>
          <CardTitle
            title="Treasury activity"
            detail="Recent checks and payment events"
            action={<Badge tone="slate">Today</Badge>}
          />
          <div className="divide-y divide-slate-100">
            <ActivityRow
              icon={Sparkles}
              title="Payment plan refreshed"
              detail="Read-only simulation · 10:42 AM"
              tone="blue"
            />
            <ActivityRow
              icon={CircleCheck}
              title="Mandate checks passed"
              detail="Version 3 · 10:36 AM"
              tone="green"
            />
            <ActivityRow
              icon={ArrowDownLeft}
              title="Safe snapshot updated"
              detail="Block 6,812,904 · 10:31 AM"
              tone="slate"
            />
            <ActivityRow
              icon={Clock3}
              title="Northstar invoice needs approval"
              detail="NSA-2026-288 · 9:58 AM"
              tone="amber"
            />
          </div>
        </Card>
      </div>
    </MockAppShell>
  );
}

function ActivityRow({
  icon: Icon,
  title,
  detail,
  tone,
}: {
  icon: typeof Sparkles;
  title: string;
  detail: string;
  tone: 'blue' | 'green' | 'slate' | 'amber';
}) {
  const styles = {
    blue: 'bg-blue-50 text-blue-700',
    green: 'bg-emerald-50 text-emerald-700',
    slate: 'bg-slate-100 text-slate-600',
    amber: 'bg-amber-50 text-amber-700',
  };
  return (
    <div className="flex items-center gap-3 py-3.5 first:pt-0 last:pb-0">
      <span
        className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl ${styles[tone]}`}
      >
        <Icon aria-hidden="true" size={16} />
      </span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-semibold text-slate-800">{title}</p>
        <p className="mt-1 truncate text-[10px] text-slate-400">{detail}</p>
      </div>
      <ArrowUpRight
        aria-hidden="true"
        size={14}
        className="shrink-0 text-slate-300"
      />
    </div>
  );
}
