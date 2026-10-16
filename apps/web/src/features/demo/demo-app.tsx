import {
  Activity,
  ArrowRight,
  ChevronDown,
  FileText,
  Landmark,
  LayoutDashboard,
  ShieldCheck,
  SlidersHorizontal,
  Upload,
  Waves,
} from 'lucide-react';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  NavLink,
  Outlet,
  Route,
  Routes,
  useNavigate,
  useSearchParams,
} from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from '@/components/ui/controls';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  SheetContent,
} from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/menus';
import { Alert } from '@/components/ui/misc';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { cn } from '@/lib/utils';

import {
  Check,
  Money,
  Pill,
  Ref,
  Row,
  SimBadge,
  statusLabel,
  utc,
} from './demo-kit';
import { DirectorPage } from './demo-director';
import { InvoiceDetailPage } from './demo-invoice';
import {
  ACTORS,
  FX,
  U,
  dispatch,
  nextAuto,
  o1HoldA,
  surplus,
  tHoldA,
  tProtected,
  tUncommitted,
  useScenario,
  type Role,
  type ScenarioState,
} from './scenario';

/** Routes under /demo. The director panel opens in its own window, off camera. */
export function DemoRoutes() {
  return (
    <Routes>
      <Route path="director" element={<DirectorPage />} />
      <Route element={<DemoShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="controls" element={<ControlsPage />} />
        <Route path="invoices" element={<InvoicesPage />} />
        <Route path="invoices/:id" element={<InvoiceDetailPage />} />
        <Route path="liquidity" element={<LiquidityPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="architecture" element={<ArchitecturePage />} />
        <Route path="outcome" element={<OutcomePage />} />
      </Route>
    </Routes>
  );
}

/** Runs automatic scenario events (playback), dropping callbacks from older runs. */
function useEngine(s: ScenarioState) {
  useEffect(() => {
    const auto = nextAuto(s);
    if (!auto) return;
    const timer = window.setTimeout(
      () => dispatch(auto.event, s.runId),
      auto.delayMs,
    );
    return () => window.clearTimeout(timer);
  }, [s]);
}

const NAV = [
  { to: '/demo', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/demo/controls', label: 'Controls', icon: SlidersHorizontal },
  { to: '/demo/invoices', label: 'Invoices', icon: FileText },
  { to: '/demo/liquidity', label: 'Liquidity', icon: Waves },
  { to: '/demo/audit', label: 'Audit', icon: ShieldCheck },
];

function DemoShell() {
  const s = useScenario();
  useEngine(s);
  const actor = ACTORS[s.role];
  return (
    <div className="flex min-h-dvh flex-col bg-background text-foreground">
      <header className="flex h-14 items-center gap-3 border-b bg-surface px-4">
        <Landmark className="size-5 text-primary" aria-hidden="true" />
        <span className="font-semibold">TreasuryPilot</span>
        <span className="text-subtle-foreground">/</span>
        <span className="font-medium">{FX.org}</span>
        <Badge tone="warning" className="ml-2 font-semibold">
          {FX.envLabel}
        </Badge>
        <div className="ml-auto flex items-center gap-3">
          <span className="num text-sm text-muted-foreground">
            Scenario time{' '}
            <span className="text-foreground">{utc(s.clock)}</span>
          </span>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="sm">
                <span className="text-muted-foreground">Demo role</span>
                <span className="font-semibold">
                  {actor.name} · {actor.title}
                </span>
                <ChevronDown aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                Demo role (not authentication)
              </DropdownMenuLabel>
              {(Object.keys(ACTORS) as Role[]).map((role) => (
                <DropdownMenuItem
                  key={role}
                  onSelect={() => dispatch({ type: 'SET_ROLE', role })}
                >
                  {ACTORS[role].name} · {ACTORS[role].title}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav className="w-52 shrink-0 border-r bg-surface p-3">
          <ul className="grid gap-1">
            {NAV.map(({ to, label, icon: Icon, end }) => (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2 rounded-md px-2.5 py-2 text-base font-medium text-muted-foreground hover:bg-muted hover:text-foreground',
                      isActive && 'bg-primary-muted text-foreground',
                    )
                  }
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {label}
                </NavLink>
              </li>
            ))}
          </ul>
          <div className="mt-6 rounded-md border bg-surface-muted p-2.5 text-xs text-muted-foreground">
            <p className="font-medium text-foreground">Agent</p>
            <AgentStatusPill status={s.agent} />
          </div>
        </nav>
        <main className="min-w-0 flex-1 overflow-y-auto">
          <div className="mx-auto grid max-w-6xl gap-5 px-6 py-6">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  );
}

export function AgentStatusPill({
  status,
}: {
  status: ScenarioState['agent'];
}) {
  return (
    <span data-testid="agent-status" className="mt-1 inline-block">
      {status === 'ACTIVE' && <Pill tone="success">Active</Pill>}
      {status === 'PAUSING' && <Pill tone="warning">Pausing…</Pill>}
      {status === 'PAUSED' && <Pill tone="danger">Paused</Pill>}
    </span>
  );
}

function PageTitle({
  title,
  description,
  action,
}: {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        {description && (
          <p className="mt-1 text-base text-muted-foreground">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}

// ---------------------------------------------------------------- Overview

function OverviewPage() {
  const s = useScenario();
  const navigate = useNavigate();
  const [open, setOpen] = useState<'t' | 'o1' | null>(null);
  const b = s.balances;
  const unknown = s.a.status === 'OUTCOME_UNKNOWN';
  const cash = b.t + b.o1 + b.o2;
  return (
    <>
      <PageTitle
        title="Overview"
        description={`Liquidity snapshot · ${utc(s.clock)}`}
      />
      <div className="grid grid-cols-3 gap-4">
        <Stat label="Cash on wallets" value={cash} hint="T + O1 + O2" />
        <Stat
          label="Supplied to Aave"
          value={b.aave}
          hint="Allowed pool · no debt"
        />
        <Stat
          label="Total assets (nominal)"
          value={cash + b.aave}
          hint="Not the same as spendable cash"
        />
      </div>

      <Card>
        <CardHeader
          title="Wallets"
          description="Enterprise Safes in this workspace"
        />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Wallet</TableHead>
              <TableHead className="text-right">Balance</TableHead>
              <TableHead className="text-right">Protected</TableHead>
              <TableHead className="text-right">Free</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow className="cursor-pointer" onClick={() => setOpen('t')}>
              <TableCell>
                <p className="font-medium">T / Treasury</p>
                <p className="text-xs text-muted-foreground">
                  SAFE_T · floor 100
                </p>
              </TableCell>
              <TableCell className="text-right">
                <Money value={b.t} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={b.t - tUncommitted(s)} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={tUncommitted(s)} />
              </TableCell>
              <TableCell className="text-right">
                <Button
                  size="sm"
                  variant="secondary"
                  data-testid="treasury-t-breakdown"
                  onClick={(e) => {
                    e.stopPropagation();
                    setOpen('t');
                  }}
                >
                  View breakdown
                </Button>
              </TableCell>
            </TableRow>
            <TableRow className="cursor-pointer" onClick={() => setOpen('o1')}>
              <TableCell>
                <p className="font-medium">O1 / Vendor payments</p>
                <p className="text-xs text-muted-foreground">
                  SAFE_O1 · buffer = target = 100
                </p>
              </TableCell>
              <TableCell className="text-right">
                {unknown ? (
                  <span className="grid justify-items-end">
                    <Money value={s.verified.o1} />
                    <span className="text-xs text-warning-foreground">
                      Last verified · Refresh pending
                    </span>
                  </span>
                ) : (
                  <Money value={b.o1} />
                )}
              </TableCell>
              <TableCell className="text-right">
                <Money value={FX.o1Buffer + o1HoldA(s)} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={b.o1 - FX.o1Buffer - o1HoldA(s)} />
              </TableCell>
              <TableCell className="text-right">
                <Button size="sm" variant="ghost">
                  Details
                </Button>
              </TableCell>
            </TableRow>
            <TableRow>
              <TableCell>
                <p className="font-medium">O2 / Payroll</p>
                <p className="text-xs text-muted-foreground">
                  SAFE_O2 · funded at payroll window (Oct 18)
                </p>
              </TableCell>
              <TableCell className="text-right">
                <Money value={b.o2} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={0n} />
              </TableCell>
              <TableCell className="text-right">
                <Money value={0n} />
              </TableCell>
              <TableCell />
            </TableRow>
            <TableRow>
              <TableCell>
                <p className="font-medium">Aave position</p>
                <p className="text-xs text-muted-foreground">
                  AAVE_POOL_TEST · exposure cap 3,500 · accrued interest 0
                  (simulator)
                </p>
              </TableCell>
              <TableCell className="text-right">
                <Money value={b.aave} />
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                Supplied
              </TableCell>
              <TableCell className="text-right text-muted-foreground">
                —
              </TableCell>
              <TableCell />
            </TableRow>
          </TableBody>
        </Table>
      </Card>

      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="Upcoming obligations"
            description="Approved payments with reserves"
          />
          <CardContent className="grid gap-2">
            <Obligation
              number={FX.b.number}
              payee={FX.b.payee}
              amount={FX.b.amount}
              due={FX.b.dueAt}
              via="O2"
            />
            {s.cApproved && (
              <Obligation
                number={FX.c.number}
                payee={FX.c.payee}
                amount={FX.c.amount}
                due={FX.c.dueAt}
                via="O1"
              />
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Tasks" />
          <CardContent className="grid gap-2">
            {s.a.status === 'ABSENT' ||
            s.a.status === 'EXTRACTING' ||
            s.a.status === 'DRAFT' ? (
              <button
                type="button"
                onClick={() => navigate('/demo/invoices')}
                className="flex items-center gap-3 rounded-md border p-3 text-left hover:bg-surface-muted"
              >
                <FileText
                  className="size-4 text-muted-foreground"
                  aria-hidden="true"
                />
                <span className="flex-1">
                  <span className="block font-medium">Review cloud bill</span>
                  <span className="block text-sm text-muted-foreground">
                    Document received · not reviewed · no approval yet
                  </span>
                </span>
                <Pill tone="neutral">To do</Pill>
              </button>
            ) : (
              <p className="text-sm text-muted-foreground">
                No open tasks for {ACTORS[s.role].name}.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={open !== null}
        onOpenChange={(value) => !value && setOpen(null)}
      >
        {open === 't' && <TBreakdown s={s} />}
        {open === 'o1' && <O1Breakdown s={s} />}
      </Dialog>
    </>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: bigint;
  hint: string;
}) {
  return (
    <Card className="p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl">
        <Money value={value} />
      </p>
      <p className="mt-1 text-xs text-subtle-foreground">{hint}</p>
    </Card>
  );
}

function Obligation({
  number,
  payee,
  amount,
  due,
  via,
}: {
  number: string;
  payee: string;
  amount: bigint;
  due: string;
  via: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-md border p-3">
      <div className="flex-1">
        <p className="font-medium">
          {number}{' '}
          <span className="font-normal text-muted-foreground">· {payee}</span>
        </p>
        <p className="text-sm text-muted-foreground">
          Due {utc(due, false)} · pays via {via} · reserved at T
        </p>
      </div>
      <Money value={amount} />
      <Pill tone="info">Scheduled · Reserved</Pill>
    </div>
  );
}

export function TBreakdown({ s }: { s: ScenarioState }) {
  const hold = tHoldA(s);
  return (
    <SheetContent width="md" aria-describedby={undefined}>
      <div className="border-b p-5">
        <DialogTitle>T / Treasury breakdown</DialogTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Snapshot {utc(s.clock)}
        </p>
      </div>
      <div className="grid gap-1 p-5 text-base">
        <Row label="Balance" value={s.balances.t} className="pb-3 text-lg" />
        <Row
          label="Payroll reserve"
          hint="PAYROLL-017 · due Oct 18"
          value={FX.b.amount}
        />
        {s.cApproved && (
          <Row
            label="Bill reserve"
            hint="INV-DATA-018 · due Oct 19"
            value={FX.c.amount}
          />
        )}
        <Row label="Floor" value={FX.tFloor} />
        {hold > 0n && (
          <Row
            label="Funding hold · INV-CLOUD-042"
            hint={
              hold < FX.a.early
                ? `${(FX.a.early - hold) / U} more comes from the Aave withdrawal`
                : undefined
            }
            value={hold}
          />
        )}
        <Row
          strong
          label={
            s.a.status === 'ABSENT' || !s.a.approvalRef
              ? 'Free before A'
              : 'Uncommitted'
          }
          value={tUncommitted(s)}
        />
        <p className="mt-3 text-xs text-subtle-foreground">
          Reserves are enforced by backend policy in this simulation, not by an
          on-chain hard reserve.
        </p>
      </div>
    </SheetContent>
  );
}

function O1Breakdown({ s }: { s: ScenarioState }) {
  const unknown = s.a.status === 'OUTCOME_UNKNOWN';
  const balance = unknown ? s.verified.o1 : s.balances.o1;
  const hold = o1HoldA(s);
  return (
    <SheetContent width="md" aria-describedby={undefined}>
      <div className="border-b p-5">
        <DialogTitle>O1 / Vendor payments</DialogTitle>
        <p className="mt-1 text-sm text-muted-foreground">
          Snapshot {utc(s.clock)}
        </p>
      </div>
      <div className="grid gap-1 p-5">
        <Row
          label={unknown ? 'Last verified balance' : 'Balance'}
          hint={unknown ? 'Refresh pending' : undefined}
          value={balance}
          className="pb-3 text-lg"
        />
        {hold > 0n && (
          <Row label="Execution hold · INV-CLOUD-042" value={hold} />
        )}
        <Row label="Buffer (target 100)" value={FX.o1Buffer} />
        <Row strong label="Spendable" value={balance - FX.o1Buffer - hold} />
      </div>
    </SheetContent>
  );
}

// ---------------------------------------------------------------- Controls

function ControlsPage() {
  const s = useScenario();
  const [params, setParams] = useSearchParams();
  const [confirm, setConfirm] = useState(false);
  const tab = params.get('tab') ?? 'mandate';
  const day = s.dayPlusOne;
  const used = {
    withdraw: !day && s.a.steps.withdraw === 'Confirmed' ? 210n * U : 0n,
    refill: !day && s.a.steps.refill === 'Confirmed' ? FX.a.early : 0n,
    pay: !day && s.a.status === 'PAID' ? FX.a.early : 0n,
    supply: s.supply === 'CONFIRMED' ? 1_310n * U : 0n,
  };
  return (
    <>
      <PageTitle
        title="Controls"
        description="Owner-granted authority for the agent"
      />
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value })}>
        <TabsList>
          <TabsTrigger value="mandate">Mandate</TabsTrigger>
          <TabsTrigger value="agent">Agent controls</TabsTrigger>
        </TabsList>
        <TabsContent value="mandate" className="mt-4 grid gap-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  Mandate v7 <Pill tone="success">Active</Pill>
                </span>
              }
              description={`Granted by owner Minh · expires ${utc(FX.mandate.expiresAt, false)} · one asset, one chain, one pool`}
              action={
                <span className="text-sm text-muted-foreground">
                  Read only
                  {s.role !== 'OWNER' ? ` for ${ACTORS[s.role].title}` : ''}
                </span>
              }
            />
            <CardContent className="grid grid-cols-2 gap-6">
              <div className="grid gap-3">
                <Section title="Allowed actions">
                  <div className="flex flex-wrap gap-1.5">
                    {['WITHDRAW', 'REFILL', 'PAY', 'SUPPLY'].map((a) => (
                      <Pill key={a} tone="outline">
                        {a}
                      </Pill>
                    ))}
                    <Pill tone="neutral">
                      BORROW · requires separate owner authorization
                    </Pill>
                  </div>
                </Section>
                <Section title="Approved payees (must be Active)">
                  <ul className="grid gap-1 text-sm">
                    <li>
                      Northstar Cloud Vendor · <Ref>VENDOR_CLOUD</Ref>{' '}
                      <Pill tone="success">Active</Pill>
                    </li>
                    <li>
                      Payroll settlement · <Ref>PAYROLL_RECIPIENT</Ref>{' '}
                      <Pill tone="success">Active</Pill>
                    </li>
                    <li>
                      Data infrastructure vendor · <Ref>VENDOR_DATA</Ref>{' '}
                      <Pill tone="success">Active</Pill>
                    </li>
                  </ul>
                  <p className="mt-2 text-sm">
                    Unknown payee: <Pill tone="danger">BLOCK</Pill>
                  </p>
                </Section>
                <Section title="Asset, pool, paths">
                  <ul className="grid gap-1 text-sm text-muted-foreground">
                    <li>Asset: USDC (usdc-test)</li>
                    <li>
                      Pool: Allowed Aave integration · <Ref>AAVE_POOL_TEST</Ref>
                    </li>
                    <li>Refill paths: T → O1, T → O2</li>
                    <li>
                      Reserve horizon 7 days · withdraw margin 5% · min supply
                      200
                    </li>
                    <li>No re-supply on the same UTC day as a withdrawal</li>
                  </ul>
                </Section>
              </div>
              <div className="grid content-start gap-3">
                <Section title="Limits · counters are separate per action">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Action</TableHead>
                        <TableHead className="text-right">Per tx</TableHead>
                        <TableHead className="text-right">Daily</TableHead>
                        <TableHead className="text-right">Used today</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      <LimitRow
                        action="PAY"
                        perTx={FX.mandate.perTx}
                        daily={FX.mandate.daily}
                        used={used.pay}
                      />
                      <LimitRow
                        action="REFILL"
                        perTx={FX.mandate.perTx}
                        daily={FX.mandate.daily}
                        used={used.refill}
                      />
                      <LimitRow
                        action="WITHDRAW"
                        perTx={FX.mandate.perTx}
                        daily={FX.mandate.daily}
                        used={used.withdraw}
                      />
                      <LimitRow
                        action="SUPPLY"
                        perTx={FX.mandate.perTx}
                        daily={FX.mandate.supplyDaily}
                        used={used.supply}
                      />
                    </TableBody>
                  </Table>
                  <p className="mt-2 text-sm text-muted-foreground">
                    Pool exposure cap:{' '}
                    <Money value={FX.mandate.maxPoolExposure} />
                  </p>
                </Section>
                <Section title="Gas budget (native ETH, separate from USDC)">
                  <p className="text-sm text-muted-foreground">
                    0.001 ETH per tx · 0.01 ETH per day · balance sufficient
                  </p>
                </Section>
                <Section title="Owner controls">
                  <ul className="grid gap-1 text-sm text-muted-foreground">
                    <li>
                      Only the owner can add recipients, raise caps or grant
                      borrowing.
                    </li>
                    <li>
                      Payments still require invoice approval by an approver.
                    </li>
                    <li>The owner can pause the agent at any time.</li>
                  </ul>
                </Section>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="agent" className="mt-4 grid gap-4">
          <Card>
            <CardHeader
              title={
                <span className="flex items-center gap-2">
                  Agent <AgentStatusPill status={s.agent} />
                </span>
              }
              description="Pausing stops new agent cycles. Confirmed payments are not reversed; Safe owners keep their own powers."
              action={
                s.role === 'OWNER' ? (
                  <Button
                    variant="danger"
                    data-testid="agent-pause"
                    disabled={s.agent !== 'ACTIVE'}
                    loading={s.agent === 'PAUSING'}
                    onClick={() => setConfirm(true)}
                  >
                    {s.agent === 'PAUSING' ? 'Pausing…' : 'Pause agent'}
                  </Button>
                ) : (
                  <span className="text-sm text-muted-foreground">
                    Only the owner can pause the agent.
                  </span>
                )
              }
            />
            <CardContent>
              <ActivityList s={s} limit={6} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>Pause agent?</DialogTitle>
            <DialogDescription>
              New agent cycles stop after the pause takes effect. Already
              confirmed transactions are not reversed.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setConfirm(false)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={() => {
                dispatch({ type: 'PAUSE_REQUEST' });
                setConfirm(false);
              }}
            >
              Confirm pause
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
      {children}
    </section>
  );
}

function LimitRow({
  action,
  perTx,
  daily,
  used,
}: {
  action: string;
  perTx: bigint;
  daily: bigint;
  used: bigint;
}) {
  return (
    <TableRow>
      <TableCell className="font-medium">{action}</TableCell>
      <TableCell className="text-right">
        <Money value={perTx} />
      </TableCell>
      <TableCell className="text-right">
        <Money value={daily} />
      </TableCell>
      <TableCell className="text-right">
        <Money value={used} />
      </TableCell>
    </TableRow>
  );
}

export function ActivityList({
  s,
  limit,
}: {
  s: ScenarioState;
  limit?: number;
}) {
  const rows = [...s.activity].reverse().slice(0, limit);
  return (
    <ol className="grid gap-2">
      {rows.map((row, i) => (
        <li
          key={`${row.at}-${i}`}
          className={cn(
            'flex gap-3 rounded-md border p-2.5 text-sm',
            i === 0 && 'border-border-strong bg-surface-muted',
          )}
        >
          <Activity
            className={cn(
              'mt-0.5 size-4 shrink-0 text-muted-foreground',
              row.kind === 'block' && 'text-danger',
              row.kind === 'chain' && 'text-info',
            )}
            aria-hidden="true"
          />
          <span className="num w-40 shrink-0 text-muted-foreground">
            {utc(row.at)}
          </span>
          <span className="flex-1">{row.text}</span>
          {row.kind === 'chain' && <SimBadge />}
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- Invoices

function InvoicesPage() {
  const s = useScenario();
  const navigate = useNavigate();
  const [upload, setUpload] = useState(false);
  const rows: Array<{
    id: string;
    number: string;
    payee: string;
    amount: ReactNode;
    status: ReactNode;
    due: string;
  }> = [
    {
      id: FX.b.id,
      number: FX.b.number,
      payee: FX.b.payee,
      amount: <Money value={FX.b.amount} />,
      status: <Pill tone="info">Approved · Scheduled</Pill>,
      due: FX.b.dueAt,
    },
  ];
  if (s.a.status !== 'ABSENT') {
    rows.unshift({
      id: FX.a.id,
      number: FX.a.number,
      payee: FX.a.vendor,
      amount: (
        <span>
          <Money value={FX.a.standard} />{' '}
          <span className="text-xs text-muted-foreground">· early 980</span>
        </span>
      ),
      status: (
        <Pill
          tone={
            s.a.status === 'PAID'
              ? 'success'
              : s.a.status === 'OUTCOME_UNKNOWN'
                ? 'warning'
                : 'neutral'
          }
        >
          {statusLabel(s.a.status)}
        </Pill>
      ),
      due: FX.a.dueAt,
    });
  }
  if (s.cApproved) {
    rows.unshift({
      id: FX.c.id,
      number: FX.c.number,
      payee: FX.c.payee,
      amount: <Money value={FX.c.amount} />,
      status: <Pill tone="info">Approved · Scheduled</Pill>,
      due: FX.c.dueAt,
    });
  }
  if (s.security.loaded) {
    rows.unshift({
      id: FX.x.id,
      number: FX.x.number,
      payee: 'Unregistered recipient',
      amount: <Money value={FX.x.amount} />,
      status: s.security.blocked ? (
        <Pill tone="danger">Blocked · unknown recipient</Pill>
      ) : (
        <Pill tone="warning">Flagged review</Pill>
      ),
      due: '2026-10-24T17:00:00Z',
    });
  }
  return (
    <>
      <PageTitle
        title="Invoices"
        description="Payment requests and their approvals"
        action={
          <Button
            variant="primary"
            data-testid="invoice-upload"
            onClick={() => setUpload(true)}
          >
            <Upload aria-hidden="true" /> Upload invoice
          </Button>
        }
      />
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Invoice</TableHead>
              <TableHead>Payee</TableHead>
              <TableHead className="text-right">Amount</TableHead>
              <TableHead>Due</TableHead>
              <TableHead>Status</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={row.id}
                className="cursor-pointer"
                onClick={() => navigate(`/demo/invoices/${row.id}`)}
              >
                <TableCell>
                  <p className="font-medium">{row.number}</p>
                  <p className="font-mono text-xs text-muted-foreground">
                    {row.id}
                  </p>
                </TableCell>
                <TableCell>{row.payee}</TableCell>
                <TableCell className="text-right">{row.amount}</TableCell>
                <TableCell className="num text-sm">
                  {utc(row.due, false)}
                </TableCell>
                <TableCell>{row.status}</TableCell>
                <TableCell className="text-right">
                  <ArrowRight
                    className="inline size-4 text-muted-foreground"
                    aria-hidden="true"
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      <UploadDialog open={upload} onOpenChange={setUpload} />
    </>
  );
}

function UploadDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const s = useScenario();
  const navigate = useNavigate();
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState<string | null>(null);
  const onFile = (file: File | undefined) => {
    if (!file) return;
    if (file.name !== FX.a.fileName) {
      setError(
        `Unsupported in demo mode: only the scripted sample ${FX.a.fileName} has a recorded extraction.`,
      );
      return;
    }
    if (s.a.status === 'ABSENT') dispatch({ type: 'UPLOAD_A' });
    onOpenChange(false);
    navigate(`/demo/invoices/${FX.a.id}?tab=review`);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        setError(null);
        onOpenChange(value);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Upload invoice</DialogTitle>
          <DialogDescription>
            A draft is prepared from the document. Finance reviews every field
            before anything is submitted.
          </DialogDescription>
        </DialogHeader>
        <button
          type="button"
          onClick={() => input.current?.click()}
          className="grid place-items-center gap-2 rounded-lg border border-dashed bg-surface-muted p-8 text-center hover:bg-muted"
        >
          <Upload className="size-6 text-muted-foreground" aria-hidden="true" />
          <span className="font-medium">Choose a PDF invoice</span>
          <span className="text-sm text-muted-foreground">
            Demo mode: recorded extraction fixture
          </span>
        </button>
        <input
          ref={input}
          type="file"
          accept="application/pdf"
          className="hidden"
          onChange={(e) => {
            onFile(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
        {error && (
          <Alert tone="warning" title="Unsupported file">
            {error}
          </Alert>
        )}
        {s.a.status !== 'ABSENT' && (
          <Alert tone="info">
            INV-CLOUD-042 was already uploaded; choosing it again opens the
            existing request.
          </Alert>
        )}
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------- Liquidity

function LiquidityPage() {
  const s = useScenario();
  const [view, setView] = useState<'allocation' | 'supply' | null>(null);
  const protectedT = tProtected(s);
  const amount = s.supply === 'CONFIRMED' ? 1_310n * U : surplus(s);
  const exposureAfter =
    s.supply === 'CONFIRMED' ? s.balances.aave : s.balances.aave + amount;
  return (
    <>
      <PageTitle
        title="Liquidity"
        description={`Reserve-first allocation · ${utc(s.clock)}`}
        action={
          <div className="flex gap-2">
            <Button
              data-testid="liquidity-allocation"
              onClick={() => setView('allocation')}
            >
              View allocation
            </Button>
            <Button onClick={() => setView('supply')} disabled={!s.dayPlusOne}>
              View supply plan
            </Button>
          </div>
        }
      />
      <div className="grid grid-cols-4 gap-4">
        <Stat
          label="T / Treasury"
          value={s.balances.t}
          hint="Confirmed balance"
        />
        <Stat
          label="Protected at T"
          value={protectedT}
          hint="Obligations + floor"
        />
        <Stat
          label="Surplus (uncommitted)"
          value={tUncommitted(s) > 0n ? tUncommitted(s) : 0n}
          hint="Only confirmed cash counts"
        />
        <Stat label="Aave position" value={s.balances.aave} hint="Cap 3,500" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader
            title="Events"
            description="Revenue counts only after confirmation"
          />
          <CardContent className="grid gap-2 text-sm">
            {s.dayPlusOne ? (
              <>
                <div className="flex items-center justify-between rounded-md border p-3">
                  <span>
                    Revenue received at T{' '}
                    <SimBadge>Confirmed · simulated</SimBadge>
                  </span>
                  <Money
                    value={FX.revenue}
                    sign="+"
                    className="text-success-foreground"
                  />
                </div>
                <div className="flex items-center justify-between rounded-md border p-3">
                  <span>
                    INV-DATA-018 approved separately by An ·{' '}
                    <Ref>{FX.c.approvalRef}</Ref>
                  </span>
                  <span className="text-muted-foreground">
                    Reserve <Money value={FX.c.amount} />
                  </span>
                </div>
              </>
            ) : (
              <p className="text-muted-foreground">
                No new revenue today. Same-UTC-day re-supply after a withdrawal
                is not allowed.
              </p>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader
            title="Supply cycle"
            description={
              s.dayPlusOne
                ? `Scheduled cycle ${utc(FX.clock.supplyCycle)}`
                : 'No cycle on Day D'
            }
          />
          <CardContent className="grid gap-2 text-sm">
            {s.supply === 'NONE' && (
              <p className="text-muted-foreground">Nothing to supply.</p>
            )}
            {s.supply === 'WAITING_CYCLE' && (
              <Pill tone="neutral">Waiting for scheduled cycle</Pill>
            )}
            {s.supply === 'SUBMITTED' && (
              <Pill tone="info">SUPPLY 1,310 submitted · {FX.refs.supply}</Pill>
            )}
            {s.supply === 'CONFIRMED' && (
              <>
                <p>
                  <Pill tone="success">SUPPLY 1,310 confirmed</Pill>{' '}
                  <Ref>{FX.refs.supply}</Ref> <SimBadge />
                </p>
                <p className="text-muted-foreground">
                  PAYROLL-017 and INV-DATA-018 not paid yet · reserves intact at
                  T (<Money value={protectedT} />
                  ).
                </p>
              </>
            )}
            <p className="text-xs text-subtle-foreground">
              No yield is realized or guaranteed. Accrued interest is 0 in the
              simulator.
            </p>
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={view !== null}
        onOpenChange={(value) => !value && setView(null)}
      >
        {view === 'allocation' && (
          <SheetContent width="md" aria-describedby={undefined}>
            <div className="border-b p-5">
              <DialogTitle>Allocation at T</DialogTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Snapshot {utc(s.clock)}
              </p>
            </div>
            <div
              className="grid gap-1 p-5"
              data-testid="liquidity-allocation-detail"
            >
              <Row label="T balance (confirmed)" value={s.balances.t} />
              <Row
                label="PAYROLL-017 reserve"
                hint="Approval B · due Oct 18"
                value={FX.b.amount}
                sign="-"
              />
              {s.cApproved && (
                <Row
                  label="INV-DATA-018 reserve"
                  hint="Approval C · due Oct 19"
                  value={FX.c.amount}
                  sign="-"
                />
              )}
              <Row label="T floor" value={FX.tFloor} sign="-" />
              {tHoldA(s) > 0n && (
                <Row label="Funding hold A" value={tHoldA(s)} sign="-" />
              )}
              <Row
                strong
                label="Surplus"
                value={tUncommitted(s) > 0n ? tUncommitted(s) : 0n}
              />
              <p className="mt-3 rounded-md bg-surface-muted p-3 font-mono text-sm">
                {usdExpr(s)}
              </p>
              <p className="mt-2 text-xs text-subtle-foreground">
                B and C are separate obligations with their own approvals. The
                O1 buffer is not counted as T surplus.
              </p>
            </div>
          </SheetContent>
        )}
        {view === 'supply' && (
          <SheetContent width="md" aria-describedby={undefined}>
            <div className="border-b p-5">
              <DialogTitle>Supply plan</DialogTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Executes at the scheduled cycle · no manual send
              </p>
            </div>
            <div className="grid gap-4 p-5">
              <div className="grid gap-1">
                <Row label="SUPPLY T → Aave" value={amount} />
                <Row
                  label="Exposure after"
                  hint={`Cap ${'3,500'} USDC`}
                  value={exposureAfter}
                />
              </div>
              <ul className="grid gap-1.5">
                <Check>Amount ≤ per-tx and daily supply cap (2,000)</Check>
                <Check>Exposure after ≤ pool cap (3,100 / 3,500)</Check>
                <Check>Above minimum supply (200)</Check>
                <Check>
                  Pool enabled and health check pass · no treasury debt
                </Check>
                <Check>
                  Last withdrawal was Oct 16; supply on Oct 17 (no same-UTC-day
                  re-supply)
                </Check>
                <Check>Gas quote within ETH caps</Check>
                <Check>
                  Fee / risk / economic check: PASS (synthetic assumption)
                </Check>
                <Check>
                  Reserves for PAYROLL-017, INV-DATA-018 and floor stay at T
                </Check>
              </ul>
              <p className="text-sm text-muted-foreground">
                Status:{' '}
                {s.supply === 'WAITING_CYCLE'
                  ? 'Waiting for scheduled cycle'
                  : s.supply === 'SUBMITTED'
                    ? 'Submitted'
                    : s.supply === 'CONFIRMED'
                      ? 'Confirmed'
                      : '—'}
              </p>
            </div>
          </SheetContent>
        )}
      </Dialog>
    </>
  );
}

function usdExpr(s: ScenarioState) {
  const parts = [
    s.balances.t,
    FX.b.amount,
    ...(s.cApproved ? [FX.c.amount] : []),
    FX.tFloor,
    ...(tHoldA(s) > 0n ? [tHoldA(s)] : []),
  ];
  const fmt = (v: bigint) => (v / U).toLocaleString('en-US');
  const result = tUncommitted(s) > 0n ? tUncommitted(s) : 0n;
  return `${parts.map(fmt).join(' - ')} = ${fmt(result)}`;
}

// ---------------------------------------------------------------- Audit

function AuditPage() {
  const s = useScenario();
  const [report, setReport] = useState(false);
  return (
    <>
      <PageTitle title="Audit" description="Security evidence and activity" />
      <Card data-testid="security-block">
        <CardHeader
          title="Security test evidence"
          description="App validation and contract-boundary test are shown separately"
        />
        <CardContent className="grid grid-cols-2 gap-4">
          <div className="rounded-md border p-4">
            <p className="flex items-center gap-2 font-semibold">
              1 · App validation <Pill tone="info">This session</Pill>
            </p>
            {s.security.blocked ? (
              <ul className="mt-2 grid gap-1 text-sm">
                <li>
                  <Pill tone="danger">BLOCKED_UNKNOWN_RECIPIENT</Pill>
                </li>
                <li>
                  INV-CLOUD-043 · 250 USDC · recipient{' '}
                  <Ref>UNKNOWN_RECIPIENT</Ref>
                </li>
                <li className="text-muted-foreground">
                  No approval, reserve, plan or payment created. Ledger
                  unchanged.
                </li>
              </ul>
            ) : (
              <p className="mt-2 text-sm text-muted-foreground">
                No blocked submissions yet.
              </p>
            )}
          </div>
          <div className="rounded-md border p-4">
            <p className="flex items-center gap-2 font-semibold">
              2 · Contract-boundary test{' '}
              <SimBadge>Simulated boundary test</SimBadge>
            </p>
            <p className="mt-2 text-sm">
              Report <Ref>{FX.x.contractTestRef}</Ref> · prepared before
              recording
            </p>
            <p className="mt-1 text-sm text-muted-foreground">
              Isolated clean fixture, not invoice A. No transaction hash or
              revert log.
            </p>
            <Button className="mt-3" size="sm" onClick={() => setReport(true)}>
              View report
            </Button>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader title="Activity" />
        <CardContent>
          <ActivityList s={s} />
        </CardContent>
      </Card>
      <Dialog open={report} onOpenChange={setReport}>
        <DialogContent size="lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              Contract-boundary test report <SimBadge>Simulated</SimBadge>
            </DialogTitle>
            <DialogDescription>
              {FX.x.contractTestRef} · source: simulation fixture, not an
              on-chain receipt
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3 text-sm">
            <Section title="Setup">
              <p className="text-muted-foreground">
                Separate clean fixture: an unspent request with valid authority,
                except a deliberate recipient/payload mutation. Invoice A
                (already paid) is not reused, so a duplicate-payment check
                cannot mask the result.
              </p>
            </Section>
            <Section title="Mutation">
              <p className="text-muted-foreground">
                PAY recipient changed from <Ref>VENDOR_CLOUD</Ref> to{' '}
                <Ref>UNKNOWN_RECIPIENT</Ref>; all other fields unchanged.
              </p>
            </Section>
            <Section title="Expected result">
              <p>
                Rejected at the executor boundary (modeled). Broadcast count: 0.
              </p>
            </Section>
            <Alert tone="warning">
              This is a simulated boundary test. It is not proof of on-chain
              enforcement until the real test is run on the exact executor path.
            </Alert>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}

// ---------------------------------------------------------------- Overlays (scenes 10–11)

function ArchitecturePage() {
  return (
    <>
      <PageTitle
        title="How the agent works"
        description="High-level logic. Owner approval, mandate and pause are control inputs, not AI output."
      />
      <Card className="p-8">
        <div className="mx-auto grid max-w-3xl justify-items-center gap-3 text-center">
          <Box tone="neutral">
            Reviewed invoice + approved obligations + wallet/pool observations
          </Box>
          <Down />
          <Box tone="primary">Agent: observe / plan / act / verify</Box>
          <Down />
          <div className="grid w-full grid-cols-3 gap-3">
            <Box tone="ai">AI drafts &amp; explains</Box>
            <Box tone="neutral">Deterministic financial engine</Box>
            <Box tone="neutral">Policy checks</Box>
          </div>
          <Down />
          <Box tone="neutral">Signer → Safe / module</Box>
          <Down />
          <Box tone="neutral">Pool / recipient</Box>
          <Down />
          <Box tone="success">Verify / reconcile</Box>
          <p className="mt-4 text-sm text-muted-foreground">
            The language model never approves payments, holds keys or calculates
            balances.
          </p>
        </div>
      </Card>
    </>
  );
}

function Box({
  tone,
  children,
}: {
  tone: 'neutral' | 'primary' | 'ai' | 'success';
  children: ReactNode;
}) {
  return (
    <div
      className={cn(
        'w-full rounded-lg border px-4 py-3 font-medium',
        tone === 'primary' && 'border-primary bg-primary-muted',
        tone === 'ai' && 'border-ai-border bg-ai-muted text-ai-foreground',
        tone === 'success' &&
          'border-success-border bg-success-muted text-success-foreground',
        tone === 'neutral' && 'bg-surface',
      )}
    >
      {children}
    </div>
  );
}
const Down = () => (
  <ChevronDown className="size-5 text-subtle-foreground" aria-hidden="true" />
);

function OutcomePage() {
  const s = useScenario();
  const lines = [
    { ok: s.a.recon === 'Matched', text: 'Invoice A: paid 980 / matched' },
    {
      ok: s.a.status === 'PAID',
      text: 'Payroll and upcoming bill reserves preserved',
    },
    {
      ok: s.a.paySubmissions === 1 && s.a.status === 'PAID',
      text: 'One payment / unknown outcome verified before completion',
    },
    {
      ok: s.supply === 'CONFIRMED' && s.agent === 'PAUSED',
      text: 'Only 1,310 surplus supplied / agent now paused',
    },
  ];
  const b = s.balances;
  return (
    <Card className="p-10">
      <h1 className="text-display font-semibold">Outcome</h1>
      <ul className="mt-6 grid gap-4 text-xl">
        {lines.map((line) => (
          <Check key={line.text} ok={line.ok}>
            {line.text}
          </Check>
        ))}
      </ul>
      <p className="num mt-8 text-base text-muted-foreground">
        Final state: T {usdShort(b.t)} · O1 {usdShort(b.o1)} · O2{' '}
        {usdShort(b.o2)} · Aave {usdShort(b.aave)} USDC · PAYROLL-017 and
        INV-DATA-018 not paid yet
      </p>
      <p className="mt-10 border-t pt-4 text-sm text-subtle-foreground">
        Synthetic business scenario. Execution/evidence mode labeled throughout.
        No guaranteed yield.
      </p>
    </Card>
  );
}
const usdShort = (v: bigint) => (v / U).toLocaleString('en-US');
