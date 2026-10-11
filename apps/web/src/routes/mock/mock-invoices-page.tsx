import { useMemo, useState } from 'react';
import {
  ArrowRight,
  Check,
  CircleAlert,
  FileCheck2,
  Filter,
  Search,
  ShieldCheck,
  UserRoundCheck,
} from 'lucide-react';

import {
  ActionButton,
  Badge,
  Card,
  CardTitle,
  MockAppShell,
  PageHeading,
} from '@/components/mock';
import {
  mockInvoices,
  money,
  statusTone,
  type InvoiceStatus,
  type MockInvoice,
} from '@/lib/mock-data';

type FilterKey = 'All' | InvoiceStatus;

const filters: { label: FilterKey; count: number }[] = [
  { label: 'All', count: mockInvoices.length },
  { label: 'Needs approval', count: 1 },
  { label: 'Approved', count: 1 },
  { label: 'In review', count: 1 },
  { label: 'Scheduled', count: 1 },
  { label: 'Paid', count: 1 },
];

export function MockInvoicesPage() {
  const [filter, setFilter] = useState<FilterKey>('All');
  const [search, setSearch] = useState('');
  const [selectedInvoice, setSelectedInvoice] = useState('NSA-2026-288');
  const [showPolicyNotes, setShowPolicyNotes] = useState(false);
  const [reviewed, setReviewed] = useState(false);

  const visibleInvoices = useMemo(
    () =>
      mockInvoices.filter((invoice) => {
        const matchesFilter = filter === 'All' || invoice.status === filter;
        const term = search.trim().toLowerCase();
        return (
          matchesFilter &&
          (!term ||
            `${invoice.vendor} ${invoice.invoice} ${invoice.status}`
              .toLowerCase()
              .includes(term))
        );
      }),
    [filter, search],
  );

  const selected =
    mockInvoices.find((invoice) => invoice.invoice === selectedInvoice) ??
    mockInvoices[0];

  return (
    <MockAppShell activePage="invoices">
      <PageHeading
        eyebrow="Acme Finance / Accounts payable"
        title="Invoices & approvals"
        description="Track supplier obligations, review flags, and see exactly what an approver would authorize."
      >
        <ActionButton
          variant="secondary"
          onClick={() => {
            setSearch('');
            setFilter('All');
          }}
        >
          Clear filters
        </ActionButton>
        <ActionButton onClick={() => setShowPolicyNotes((current) => !current)}>
          <Filter aria-hidden="true" size={14} />
          {showPolicyNotes ? 'Hide policy notes' : 'Show policy notes'}
        </ActionButton>
      </PageHeading>

      {showPolicyNotes && (
        <div
          className="mb-4 rounded-xl border border-blue-100 bg-blue-50/70 px-4 py-3 text-xs leading-5 text-blue-900"
          role="status"
        >
          Mandate preview: payment amount ≤ 2,000 USDC TEST per transaction,
          aggregate autonomous limit ≤ 10,000 USDC TEST per day, and the payee
          must be allowlisted. Only an authorized human can create a payment
          approval.
        </div>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <MiniSummary
          label="Awaiting your approval"
          value="1 request"
          tone="amber"
        />
        <MiniSummary
          label="Approved obligations"
          value="3,440 USDC TEST"
          tone="green"
        />
        <MiniSummary label="Needs a closer look" value="1 request" tone="red" />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(310px,0.75fr)]">
        <Card className="overflow-hidden">
          <CardTitle
            title="Payment requests"
            detail="Five fictional invoices · all amounts shown in USDC TEST"
            action={<Badge tone="slate">5 total</Badge>}
          />
          <div className="mb-4 flex flex-col gap-3">
            <div className="relative">
              <Search
                aria-hidden="true"
                size={15}
                className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400"
              />
              <label className="sr-only" htmlFor="invoice-search">
                Search invoices
              </label>
              <input
                id="invoice-search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search vendor or invoice number"
                className="h-10 w-full rounded-xl border border-slate-200 bg-white pl-9 pr-3 text-xs outline-none placeholder:text-slate-400 focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
              />
            </div>
            <div
              className="flex gap-1 overflow-x-auto border-b border-slate-100"
              role="group"
              aria-label="Filter requests by status"
            >
              {filters.map(({ label, count }) => (
                <button
                  key={label}
                  type="button"
                  aria-pressed={filter === label}
                  onClick={() => setFilter(label)}
                  className={`inline-flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-2.5 text-[10px] font-semibold transition ${filter === label ? 'border-blue-600 text-blue-700' : 'border-transparent text-slate-400 hover:text-slate-700'}`}
                >
                  {label}
                  <span
                    className={`rounded-full px-1.5 py-0.5 text-[9px] ${filter === label ? 'bg-blue-50 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
                  >
                    {count}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div className="-mx-4 overflow-x-auto sm:-mx-5">
            <table className="w-full min-w-[620px] text-left">
              <thead>
                <tr className="bg-slate-50 text-[10px] font-semibold text-slate-400">
                  <th className="px-4 py-3 sm:px-5">Supplier</th>
                  <th className="px-3 py-3">Invoice</th>
                  <th className="px-3 py-3">Amount</th>
                  <th className="px-3 py-3">Due date</th>
                  <th className="px-3 py-3">Status</th>
                  <th className="px-3 py-3 sm:px-5">
                    <span className="sr-only">Select</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleInvoices.map((invoice) => (
                  <InvoiceRow
                    key={invoice.invoice}
                    invoice={invoice}
                    selected={selectedInvoice === invoice.invoice}
                    onSelect={() => {
                      setSelectedInvoice(invoice.invoice);
                      setReviewed(false);
                    }}
                  />
                ))}
              </tbody>
            </table>
            {visibleInvoices.length === 0 && (
              <p className="px-5 py-12 text-center text-xs text-slate-500">
                No invoices match this filter.
              </p>
            )}
          </div>
          <div className="mt-4 flex items-center justify-between text-[10px] text-slate-400">
            <span>
              Showing {visibleInvoices.length} of {mockInvoices.length} requests
            </span>
            <span>Demo data · Updated Oct 11, 2026</span>
          </div>
        </Card>

        <Card className="h-fit">
          <CardTitle
            title="Request review"
            detail={`Selected invoice · ${selected.invoice}`}
            action={
              <Badge
                tone={
                  selected.risk === 'High'
                    ? 'red'
                    : selected.risk === 'Review'
                      ? 'amber'
                      : 'green'
                }
              >
                {selected.risk} risk
              </Badge>
            }
          />
          <div className="rounded-xl border border-slate-100 bg-slate-50/70 p-3.5">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-xl bg-white text-sm font-bold text-blue-700 shadow-sm">
                {selected.initials}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-bold">{selected.vendor}</p>
                <p className="mt-0.5 text-[10px] text-slate-400">
                  {selected.invoice} · Due {selected.due}
                </p>
              </div>
              <p className="text-right text-sm font-bold">
                {money(selected.amount)}
                <span className="ml-1 text-[10px] font-medium text-slate-400">
                  USDC TEST
                </span>
              </p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            <ReviewLine
              icon={ShieldCheck}
              label="Payee allowlist"
              value={
                selected.status === 'In review'
                  ? 'Needs owner review'
                  : 'Verified'
              }
              tone={selected.status === 'In review' ? 'amber' : 'green'}
            />
            <ReviewLine
              icon={FileCheck2}
              label="Invoice fingerprint"
              value="No duplicate found"
              tone="green"
            />
            <ReviewLine
              icon={CircleAlert}
              label="Mandate cap"
              value={
                selected.amount > 2000
                  ? 'Above 2,000 USDC TEST'
                  : 'Within per-payment limit'
              }
              tone={selected.amount > 2000 ? 'red' : 'green'}
            />
            <ReviewLine
              icon={UserRoundCheck}
              label="Maker-checker"
              value="Approver required"
              tone="blue"
            />
          </div>
          <div
            className={`mt-4 rounded-xl border p-3.5 text-[11px] leading-5 ${selected.risk === 'High' ? 'border-rose-100 bg-rose-50/70 text-rose-900' : 'border-blue-100 bg-blue-50/70 text-blue-900'}`}
          >
            <p className="font-semibold">Review note</p>
            <p className="mt-1">{selected.note}</p>
          </div>
          {selected.amount > 2000 && (
            <div
              className="mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3.5 py-3 text-[10px] leading-5 text-amber-900"
              role="alert"
            >
              This request exceeds the configured autonomous per-transaction
              cap. It cannot proceed under the current mandate.
            </div>
          )}
          <div className="mt-4 rounded-xl border border-slate-200 p-3.5">
            <p className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-400">
              Exact payment fields
            </p>
            <dl className="mt-2 space-y-2 text-[10px]">
              <Field label="Payee address" value={selected.payee} />
              <Field label="Asset / network" value="USDC TEST · Sepolia TEST" />
              <Field label="Authorization" value="EIP-712 · invoice-bound" />
            </dl>
          </div>
          <div className="mt-4 space-y-2">
            <ActionButton
              className="w-full"
              disabled={selected.amount > 2000}
              onClick={() => setReviewed(true)}
            >
              {reviewed ? (
                <>
                  <Check aria-hidden="true" size={14} /> Review noted in this
                  preview
                </>
              ) : (
                <>
                  Acknowledge review note{' '}
                  <ArrowRight aria-hidden="true" size={14} />
                </>
              )}
            </ActionButton>
            <p className="text-center text-[10px] leading-4 text-slate-400">
              This acknowledges the review note only. Payment authorization
              still requires an approver to sign the exact fields using their
              wallet.
            </p>
          </div>
        </Card>
      </div>
    </MockAppShell>
  );
}

function InvoiceRow({
  invoice,
  selected,
  onSelect,
}: {
  invoice: MockInvoice;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <tr
      className={`border-t border-slate-100 text-xs transition ${selected ? 'bg-blue-50/45' : 'hover:bg-slate-50/80'}`}
    >
      <td className="px-4 py-3.5 sm:px-5">
        <span className="font-semibold text-slate-800">{invoice.vendor}</span>
      </td>
      <td className="px-3 py-3.5 text-slate-500">{invoice.invoice}</td>
      <td className="px-3 py-3.5 font-semibold">
        {money(invoice.amount)}{' '}
        <span className="text-[10px] font-normal text-slate-400">
          USDC TEST
        </span>
      </td>
      <td className="px-3 py-3.5 text-slate-500">{invoice.due}</td>
      <td className="px-3 py-3.5">
        <Badge tone={statusTone(invoice.status)}>{invoice.status}</Badge>
      </td>
      <td className="px-3 py-3.5 sm:px-5">
        <button
          type="button"
          onClick={onSelect}
          aria-label={`Review ${invoice.invoice}`}
          aria-pressed={selected}
          className={`inline-flex items-center gap-1 font-semibold ${selected ? 'text-blue-700' : 'text-slate-400 hover:text-blue-700'}`}
        >
          Review <ArrowRight aria-hidden="true" size={13} />
        </button>
      </td>
    </tr>
  );
}

function ReviewLine({
  icon: Icon,
  label,
  value,
  tone,
}: {
  icon: typeof ShieldCheck;
  label: string;
  value: string;
  tone: 'green' | 'amber' | 'red' | 'blue';
}) {
  const color = {
    green: 'text-emerald-700',
    amber: 'text-amber-700',
    red: 'text-rose-700',
    blue: 'text-blue-700',
  };
  return (
    <div className="flex items-center gap-2.5">
      <Icon aria-hidden="true" size={15} className="shrink-0 text-slate-400" />
      <span className="flex-1 text-[11px] text-slate-500">{label}</span>
      <span className={`text-[10px] font-semibold ${color[tone]}`}>
        {value}
      </span>
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right font-semibold text-slate-700">{value}</dd>
    </div>
  );
}

function MiniSummary({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: 'amber' | 'green' | 'red';
}) {
  const color = {
    amber: 'text-amber-800',
    green: 'text-emerald-800',
    red: 'text-rose-800',
  };
  return (
    <Card className="p-4">
      <p className="text-[11px] text-slate-500">{label}</p>
      <p className={`mt-2 text-lg font-bold tracking-tight ${color[tone]}`}>
        {value}
      </p>
    </Card>
  );
}
