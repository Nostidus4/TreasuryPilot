import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Loader2,
  Lock,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';
import {
  Link,
  useNavigate,
  useParams,
  useSearchParams,
} from 'react-router-dom';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Checkbox,
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
  StepBadge,
  statusLabel,
  utc,
} from './demo-kit';
import {
  ACTORS,
  FX,
  U,
  dispatch,
  earlyCashCost,
  earlyNetEstimate,
  fundingGap,
  grossDiscount,
  isApprovedOrLater,
  o1NeedForA,
  tCapacityForA,
  useScenario,
  usdRounded,
  withdrawAmount,
  type ScenarioState,
} from './scenario';

export function InvoiceDetailPage() {
  const { id } = useParams();
  if (id === FX.a.id) return <InvoiceA />;
  if (id === FX.x.id) return <InvoiceX />;
  if (id === FX.b.id || id === FX.c.id) return <ScheduledInvoice id={id} />;
  return <p className="text-muted-foreground">Invoice not found.</p>;
}

function Header({
  number,
  id,
  children,
  back = true,
}: {
  number: string;
  id: string;
  children?: ReactNode;
  back?: boolean;
}) {
  return (
    <div>
      {back && (
        <Link
          to="/demo/invoices"
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Invoices
        </Link>
      )}
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold">{number}</h1>
        <span className="font-mono text-sm text-muted-foreground">{id}</span>
        {children}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Invoice A

function InvoiceA() {
  const s = useScenario();
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') ?? 'review';
  const a = s.a;
  if (a.status === 'ABSENT')
    return (
      <p className="text-muted-foreground">
        INV-CLOUD-042 has not been uploaded.
      </p>
    );
  const exec =
    a.status === 'PAID'
      ? 'Completed'
      : a.status === 'OUTCOME_UNKNOWN'
        ? 'Outcome unknown'
        : a.status === 'EXECUTING' || a.status === 'PAYMENT_SUBMITTED'
          ? 'Executing'
          : a.status === 'READY_WAITING_WINDOW'
            ? 'Waiting for window'
            : 'Not planned';
  return (
    <>
      <Header number={FX.a.number} id={FX.a.id}>
        <span className="text-sm text-muted-foreground">
          · revision {FX.a.revision}
        </span>
      </Header>
      <div className="flex flex-wrap gap-4 text-sm">
        <span>
          Invoice{' '}
          <Pill
            tone={
              a.status === 'PAID'
                ? 'success'
                : a.status === 'OUTCOME_UNKNOWN'
                  ? 'warning'
                  : 'neutral'
            }
          >
            {statusLabel(a.status)}
          </Pill>
        </span>
        <span>
          Execution{' '}
          <Pill
            tone={
              exec === 'Completed'
                ? 'success'
                : exec === 'Outcome unknown'
                  ? 'warning'
                  : 'neutral'
            }
          >
            {exec}
          </Pill>
        </span>
        <span>
          Reconciliation{' '}
          <Pill tone={a.recon === 'Matched' ? 'success' : 'neutral'}>
            {a.recon}
          </Pill>
        </span>
      </div>
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value })}>
        <TabsList>
          <TabsTrigger value="review">Review</TabsTrigger>
          <TabsTrigger value="plan" disabled={!isApprovedOrLater(a.status)}>
            Plan
          </TabsTrigger>
          <TabsTrigger
            value="execution"
            disabled={!isApprovedOrLater(a.status)}
          >
            Execution
          </TabsTrigger>
          <TabsTrigger value="evidence" disabled={!isApprovedOrLater(a.status)}>
            Evidence
          </TabsTrigger>
        </TabsList>
        <TabsContent value="review" className="mt-4">
          <ReviewTab s={s} />
        </TabsContent>
        <TabsContent value="plan" className="mt-4">
          <PlanTab s={s} />
        </TabsContent>
        <TabsContent value="execution" className="mt-4">
          <ExecutionTab s={s} />
        </TabsContent>
        <TabsContent value="evidence" className="mt-4">
          <EvidenceTab s={s} />
        </TabsContent>
      </Tabs>
    </>
  );
}

/** Source text with the extracted spans highlighted. Plain text, never HTML. */
function SourceDocument({ highlight }: { highlight: boolean }) {
  const marks = [
    'INV-CLOUD-042',
    'Northstar Cloud Vendor',
    '1,000 USDC',
    '2026-10-23 17:00 UTC',
    '2026-10-16 17:00 UTC',
    '980 USDC',
    'registered vendor address',
  ];
  const pattern = new RegExp(
    `(${marks.map((m) => m.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`,
  );
  const parts = FX.a.sourceText.split(pattern);
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-lg border bg-surface-muted">
      <div className="flex items-center gap-2 border-b bg-surface px-3 py-2 text-sm">
        <span className="font-medium">{FX.a.fileName}</span>
        <a
          className="ml-auto inline-flex items-center gap-1 text-primary hover:underline"
          href={`${import.meta.env.BASE_URL}demo/${FX.a.fileName}`}
          target="_blank"
          rel="noreferrer"
        >
          Open original <ExternalLink className="size-3" aria-hidden="true" />
        </a>
      </div>
      <div className="m-4 flex-1 rounded-md border bg-surface p-6 font-mono text-sm leading-7 shadow-float">
        <p className="mb-4 text-lg font-semibold">Northstar Cloud Vendor</p>
        <p>
          {parts.map((part, i) =>
            highlight && marks.includes(part) ? (
              <mark
                key={i}
                className="rounded-sm bg-warning-muted px-0.5 text-foreground"
              >
                {part}
              </mark>
            ) : (
              <span key={i}>{part}</span>
            ),
          )}
        </p>
      </div>
    </div>
  );
}

function ReviewTab({ s }: { s: ScenarioState }) {
  const a = s.a;
  const [approve, setApprove] = useState(false);
  const navigate = useNavigate();
  if (a.status === 'EXTRACTING') {
    return (
      <Card className="grid min-h-80 place-items-center">
        <div className="text-center">
          <Loader2
            className="mx-auto size-6 animate-spin text-muted-foreground"
            aria-hidden="true"
          />
          <p className="mt-2 font-medium">Extracting</p>
          <p className="text-sm text-muted-foreground">
            Reading INV-CLOUD-042.pdf · recorded extraction fixture
          </p>
        </div>
      </Card>
    );
  }
  const draft = a.status === 'DRAFT';
  const fields: Array<[string, ReactNode]> = [
    ['Invoice number', 'INV-CLOUD-042'],
    ['Vendor', FX.a.vendor],
    ['Standard amount', <Money key="s" value={FX.a.standard} />],
    ['Standard due', utc(FX.a.dueAt, false)],
    ['Early-payment amount (2%)', <Money key="e" value={FX.a.early} />],
    ['Early deadline', utc(FX.a.earlyDeadline, false)],
    ['Asset', 'USDC (usdc-test)'],
    ['Paying wallet', 'O1 / Vendor payments'],
  ];
  return (
    <div className="grid grid-cols-2 gap-4">
      <SourceDocument highlight />
      <Card>
        <CardHeader
          title="Extracted fields"
          description="Draft prepared by AI. Finance verifies every field."
          action={<Pill tone="ai">Recorded extraction</Pill>}
        />
        <CardContent className="grid gap-4">
          <dl className="divide-y text-base">
            {fields.map(([label, value]) => (
              <div key={label} className="flex justify-between gap-4 py-2">
                <dt className="text-muted-foreground">{label}</dt>
                <dd className="text-right font-medium">{value}</dd>
              </div>
            ))}
          </dl>
          <div className="rounded-md border border-success-border bg-success-muted p-3 text-sm text-success-foreground">
            <p className="font-medium">Payee registry match</p>
            <p>
              Northstar Cloud Vendor → <Ref>VENDOR_CLOUD</Ref> · Active ·
              cooling period complete · address from registry, not from the
              document
            </p>
          </div>
          <p className="text-sm text-muted-foreground">
            Created by Linh (Finance) · revision 1 ·{' '}
            {a.approvalRef ? (
              <>
                approval <Ref>{a.approvalRef}</Ref>
              </>
            ) : (
              'no signature'
            )}
          </p>

          {draft && (
            <>
              <label className="flex items-center gap-2 text-base">
                <Checkbox
                  data-testid="invoice-reviewed"
                  checked={a.reviewed}
                  disabled={s.role !== 'FINANCE'}
                  onCheckedChange={(value) =>
                    dispatch({ type: 'SET_REVIEWED', value: value === true })
                  }
                />
                I verified the invoice fields
              </label>
              <Button
                variant="primary"
                data-testid="submit-invoice"
                disabled={!a.reviewed || s.role !== 'FINANCE'}
                onClick={() => dispatch({ type: 'SUBMIT_A' })}
              >
                Submit for approval
              </Button>
            </>
          )}
          {a.status === 'AWAITING_APPROVAL' &&
            (s.role === 'APPROVER' ? (
              <Button variant="primary" onClick={() => setApprove(true)}>
                Review &amp; approve
              </Button>
            ) : (
              <Alert tone="info" title="Awaiting approval">
                {s.role === 'FINANCE'
                  ? 'You created this request, so you cannot approve it. A different authorized approver must approve.'
                  : 'Approval is done by an approver, not the owner.'}
              </Alert>
            ))}
          {isApprovedOrLater(a.status) && (
            <Alert tone="success" title="Approved by An">
              <Ref>{FX.a.approvalRef}</Ref> · Simulated signature ·{' '}
              {a.status === 'READY_WAITING_WINDOW'
                ? 'Plan ready - waiting for approved window'
                : statusLabel(a.status)}
              <div className="mt-2">
                <Button size="sm" onClick={() => navigate('?tab=plan')}>
                  Open plan
                </Button>
              </div>
            </Alert>
          )}
        </CardContent>
      </Card>
      <ApprovalDialog open={approve} onOpenChange={setApprove} />
    </div>
  );
}

function ApprovalDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const navigate = useNavigate();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="lg">
        <DialogHeader>
          <DialogTitle>Approve payment obligation</DialogTitle>
          <DialogDescription>
            INV-CLOUD-042 · revision 1 · approver An. This binds recipient,
            asset, wallet and revision. It does not change the mandate.
          </DialogDescription>
        </DialogHeader>
        <Table>
          <TableBody>
            {(
              [
                [
                  'Recipient',
                  <span key="r">
                    Northstar Cloud Vendor · <Ref>VENDOR_CLOUD</Ref>
                  </span>,
                ],
                ['Asset', 'USDC (usdc-test)'],
                ['Paying wallet', 'O1 / Vendor payments'],
                [
                  'Early term',
                  <span key="e">
                    <Money value={FX.a.early} /> before{' '}
                    {utc(FX.a.earlyDeadline, false)}
                  </span>,
                ],
                [
                  'Standard term',
                  <span key="s">
                    <Money value={FX.a.standard} /> by {utc(FX.a.dueAt, false)}
                  </span>,
                ],
                ['Invoice revision', '1'],
                ['Approval expires', utc(FX.a.approvalExpires, false)],
              ] as Array<[string, ReactNode]>
            ).map(([label, value]) => (
              <TableRow key={label}>
                <TableCell className="text-muted-foreground">{label}</TableCell>
                <TableCell className="text-right font-medium">
                  {value}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Alert tone="warning">
          Demo mode: this records a <strong>Simulated signature</strong>{' '}
          (SIM-APPROVAL-A-001), not an EIP-712 wallet signature.
        </Alert>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant="primary"
            data-testid="approval-confirm"
            onClick={() => {
              dispatch({ type: 'APPROVE_A' });
              onOpenChange(false);
              navigate('?tab=review');
            }}
          >
            Confirm demo approval
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function PlanTab({ s }: { s: ScenarioState }) {
  const [compare, setCompare] = useState(false);
  const [benefit, setBenefit] = useState(false);
  const [funding, setFunding] = useState(false);
  const a = s.a;
  const planStatus =
    a.status === 'APPROVED'
      ? 'Computing plan…'
      : a.status === 'READY_WAITING_WINDOW'
        ? 'Ready - waiting for approved window'
        : a.status === 'PAID'
          ? 'Completed'
          : 'Executing';
  const executed = a.steps.withdraw !== 'Planned';
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              Plan <Ref>{FX.plan.id}</Ref>{' '}
              <Pill
                tone={
                  planStatus.startsWith('Ready')
                    ? 'info'
                    : planStatus === 'Completed'
                      ? 'success'
                      : 'neutral'
                }
              >
                {planStatus}
              </Pill>
            </span>
          }
          description={`Approval ${FX.a.approvalRef} · window opens ${utc(FX.clock.window)} · plan expires ${utc(FX.clock.planExpires)} · source: Deterministic scenario model`}
        />
        <CardContent className="grid gap-4">
          <div className="flex flex-wrap items-center gap-6">
            <div>
              <p className="text-sm text-muted-foreground">Selected term</p>
              <p className="font-semibold">EARLY</p>
            </div>
            <div>
              <p className="text-sm text-muted-foreground">Selected PAY</p>
              <p className="text-lg">
                <Money value={FX.a.early} />
              </p>
            </div>
            <div className="ml-auto flex gap-2">
              <Button
                data-testid="plan-alternatives"
                onClick={() => setCompare((v) => !v)}
              >
                Compare options{' '}
                {compare ? (
                  <ChevronDown aria-hidden="true" />
                ) : (
                  <ChevronRight aria-hidden="true" />
                )}
              </Button>
              <Button
                data-testid="liquidity-shortage"
                onClick={() => setFunding(true)}
              >
                View funding breakdown
              </Button>
            </div>
          </div>
          {compare && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Option</TableHead>
                  <TableHead className="text-right">Pay</TableHead>
                  <TableHead>When</TableHead>
                  <TableHead>Funding</TableHead>
                  <TableHead>Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow>
                  <TableCell className="font-medium">Standard</TableCell>
                  <TableCell className="text-right">
                    <Money value={FX.a.standard} />
                  </TableCell>
                  <TableCell>By Oct 23 (D+7)</TableCell>
                  <TableCell>Later, from available cash</TableCell>
                  <TableCell>
                    <Pill tone="neutral">
                      Not selected · forgoes 20 discount
                    </Pill>
                  </TableCell>
                </TableRow>
                <TableRow className="bg-primary-muted">
                  <TableCell className="font-medium">Early</TableCell>
                  <TableCell className="text-right">
                    <Money value={FX.a.early} />
                  </TableCell>
                  <TableCell>Before Oct 16 17:00 UTC (D)</TableCell>
                  <TableCell>T + Aave withdrawal (company funds)</TableCell>
                  <TableCell>
                    <Pill tone="success">
                      Selected · net ≈ {usdRounded(earlyNetEstimate)}
                    </Pill>
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell className="font-medium">Borrow proposal</TableCell>
                  <TableCell className="text-right">
                    <Money value={FX.a.early} />
                  </TableCell>
                  <TableCell>D</TableCell>
                  <TableCell>Borrow against pool</TableCell>
                  <TableCell>
                    <Pill tone="neutral">
                      Not selected · requires separate owner authorization; own
                      funds cover it
                    </Pill>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          )}
          <button
            type="button"
            className="flex items-center gap-2 text-left font-medium"
            onClick={() => setBenefit((v) => !v)}
          >
            {benefit ? (
              <ChevronDown className="size-4" aria-hidden="true" />
            ) : (
              <ChevronRight className="size-4" aria-hidden="true" />
            )}
            Estimated benefit <Pill tone="warning">Synthetic assumptions</Pill>
          </button>
          {benefit && (
            <div className="max-w-md rounded-md border p-3">
              <Row label="Gross discount" value={grossDiscount} />
              <div className="flex justify-between py-1.5">
                <span className="text-muted-foreground">
                  Cash cost{' '}
                  <span className="block text-xs text-subtle-foreground">
                    980 × 4% annual × 7 / 365
                  </span>
                </span>
                <span className="num font-medium">
                  − ≈{usdRounded(earlyCashCost)} USDC
                </span>
              </div>
              <div className="flex justify-between py-1.5">
                <span className="text-muted-foreground">Fee allowance</span>
                <span className="num font-medium">
                  − {usdRounded(FX.economics.feeEstimate)} USDC
                </span>
              </div>
              <div className="flex justify-between border-t pt-2 font-semibold">
                <span>Estimated net benefit</span>
                <span className="num">
                  ≈ {usdRounded(earlyNetEstimate)} USDC
                </span>
              </div>
              <p className="mt-2 text-xs text-subtle-foreground">
                Calculated by deterministic code, not by the language model.
                Early payment only proceeds if net ≥ 5 USDC and liquidity checks
                pass.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader
          title="Steps"
          description={
            executed
              ? 'Executing automatically in the approved window'
              : 'No action executed yet'
          }
        />
        <CardContent className="grid gap-4">
          <ol className="grid gap-2">
            <PlanStep
              n={1}
              action="WITHDRAW"
              detail="Aave → T"
              amount={withdrawAmount}
              state={a.steps.withdraw}
            />
            <PlanStep
              n={2}
              action="REFILL"
              detail="T → O1"
              amount={FX.a.early}
              state={a.steps.refill}
            />
            <PlanStep
              n={3}
              action="PAY"
              detail="O1 → VENDOR_CLOUD"
              amount={FX.a.early}
              state={a.steps.pay}
            />
          </ol>
          <ul className="grid gap-1.5">
            <Check>PAYROLL-017 reserve (300) stays at T</Check>
            <Check>T floor (100) and O1 buffer (100) protected</Check>
            <Check>Within PAY / REFILL / WITHDRAW caps (2,000 per tx)</Check>
            <Check>Payee VENDOR_CLOUD Active in registry</Check>
          </ul>
          {a.status === 'READY_WAITING_WINDOW' && (
            <Alert tone="info" title="Ready - waiting for approved window">
              The agent starts automatically at {utc(FX.clock.window)}. There is
              no manual run.
            </Alert>
          )}
        </CardContent>
      </Card>
      <Dialog open={funding} onOpenChange={setFunding}>
        <SheetContent width="md" aria-describedby={undefined}>
          <div className="border-b p-5">
            <DialogTitle>Funding breakdown</DialogTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              Computed at plan time ({utc(FX.clock.planReady)})
            </p>
          </div>
          <div className="grid gap-5 p-5">
            <section>
              <h3 className="mb-1 text-sm font-semibold">O1 needs</h3>
              <Row label="Early PAY" value={FX.a.early} />
              <Row label="O1 buffer to keep" value={FX.o1Buffer} sign="+" />
              <Row label="O1 balance" value={100n * U} sign="-" />
              <Row strong label="Refill needed" value={o1NeedForA} />
            </section>
            <section>
              <h3 className="mb-1 text-sm font-semibold">
                T funding capacity for this invoice
              </h3>
              <Row label="T balance" value={1_180n * U} />
              <Row label="Payroll reserve" value={FX.b.amount} sign="-" />
              <Row label="T floor" value={FX.tFloor} sign="-" />
              <Row
                strong
                label="Capacity for this invoice"
                hint="Excluding other obligations"
                value={tCapacityForA({
                  t: 1_180n * U,
                  o1: 0n,
                  o2: 0n,
                  aave: 0n,
                })}
              />
            </section>
            <section>
              <h3 className="mb-1 text-sm font-semibold">Shortage</h3>
              <Row label="Deficit" value={fundingGap} />
              <Row
                label="Withdraw margin 5%"
                value={withdrawAmount - fundingGap}
                sign="+"
              />
              <Row strong label="Withdraw from Aave" value={withdrawAmount} />
              <p className="mt-2 text-xs text-subtle-foreground">
                The margin is not a new refill target: REFILL stays 980 and PAY
                stays 980. The extra 10 stays uncommitted at T.
              </p>
            </section>
          </div>
        </SheetContent>
      </Dialog>
    </div>
  );
}

function PlanStep({
  n,
  action,
  detail,
  amount,
  state,
  reference,
}: {
  n: number;
  action: string;
  detail: string;
  amount: bigint;
  state: ScenarioState['a']['steps']['pay'];
  reference?: string;
}) {
  return (
    <li
      className={cn(
        'flex items-center gap-3 rounded-md border p-3',
        state === 'Outcome unknown' && 'border-warning-border bg-warning-muted',
      )}
    >
      <span className="grid size-6 place-items-center rounded-full border text-xs font-semibold">
        {n}
      </span>
      <span className="w-24 font-semibold">{action}</span>
      <span className="flex-1 text-muted-foreground">{detail}</span>
      {reference && state !== 'Planned' && <Ref>{reference}</Ref>}
      <Money value={amount} />
      <StepBadge state={state} />
    </li>
  );
}

function ExecutionTab({ s }: { s: ScenarioState }) {
  const a = s.a;
  const [status, setStatus] = useState(false);
  const started = !['APPROVED', 'READY_WAITING_WINDOW'].includes(a.status);
  const unknown = a.status === 'OUTCOME_UNKNOWN';
  const preflight = [
    'Approval SIM-APPROVAL-A-001 valid (revision 1, not expired)',
    'Payee VENDOR_CLOUD Active',
    'Policy: mandate v7 limits and paths',
    'Snapshot fresh: balances and obligations',
    'Pool enabled · withdrawable ≥ 210',
    'Gas within ETH caps',
  ];
  return (
    <div className="grid gap-4" data-testid="execution-timeline">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              Execution <SimBadge>Simulated execution path</SimBadge>
            </span>
          }
          description={
            started
              ? `Started automatically at ${utc(FX.clock.window)}`
              : `Waiting for approved window ${utc(FX.clock.window)}`
          }
          action={
            started && (
              <span className="flex items-center gap-1.5 text-sm">
                <Lock className="size-4" aria-hidden="true" /> Hold A active ·{' '}
                {a.holdAt === 'O1'
                  ? 'at O1'
                  : a.holdAt === 'T'
                    ? 'at T'
                    : 'released'}
              </span>
            )
          }
        />
        <CardContent className="grid gap-4">
          <section>
            <h3 className="mb-1.5 text-sm font-semibold">Preflight</h3>
            <ul className="grid grid-cols-2 gap-1.5">
              {preflight.map((text) => (
                <Check key={text} ok={a.preflight}>
                  {text}
                </Check>
              ))}
            </ul>
          </section>
          <ol className="grid gap-2">
            <PlanStep
              n={1}
              action="WITHDRAW"
              detail="Aave → T"
              amount={withdrawAmount}
              state={a.steps.withdraw}
              reference={FX.refs.withdraw}
            />
            <PlanStep
              n={2}
              action="REFILL"
              detail="T → O1 · after read-back"
              amount={FX.a.early}
              state={a.steps.refill}
              reference={FX.refs.refill}
            />
            <PlanStep
              n={3}
              action="PAY"
              detail="O1 → VENDOR_CLOUD"
              amount={FX.a.early}
              state={a.steps.pay}
              reference={FX.refs.pay}
            />
          </ol>
          {unknown && (
            <Alert
              tone="warning"
              title="Outcome unknown · verification pending"
              data-testid="pay-outcome-unknown"
              action={
                <Button size="sm" onClick={() => setStatus(true)}>
                  View transaction status
                </Button>
              }
            >
              The RPC acknowledgement for SIM-TX-PAY-001 was lost. Unknown does
              not mean failed: the payment stays locked while the agent checks
              the existing transaction. No second payment is created.
            </Alert>
          )}
          {a.status === 'PAID' && (
            <Alert tone="success" title="Paid · existing transaction verified">
              SIM-TX-PAY-001 verified with the confirmation policy. Payment
              submissions: {a.paySubmissions}. Hold A released.
            </Alert>
          )}
          <div className="grid grid-cols-4 gap-3 text-sm">
            <Bal
              label="T"
              value={s.balances.t}
              sub={
                a.status === 'PAID' ? 'Payroll reserve 300 intact' : undefined
              }
            />
            <Bal
              label="O1"
              value={unknown ? s.verified.o1 : s.balances.o1}
              sub={unknown ? 'Last verified · Refresh pending' : undefined}
              warn={unknown}
            />
            <Bal label="Aave" value={s.balances.aave} />
            <div className="rounded-md border p-3">
              <p className="text-muted-foreground">Payment count</p>
              <p className="text-lg font-semibold">{a.paySubmissions}</p>
            </div>
          </div>
        </CardContent>
      </Card>
      <Dialog open={status} onOpenChange={setStatus}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Transaction status</DialogTitle>
            <DialogDescription>
              Read only. Verification of the existing reference.
            </DialogDescription>
          </DialogHeader>
          <Table>
            <TableBody>
              {(
                [
                  ['Reference', <Ref key="r">{FX.refs.pay}</Ref>],
                  ['Payment', <Ref key="p">{FX.refs.payment}</Ref>],
                  ['Amount', <Money key="m" value={FX.a.early} />],
                  ['Recipient', 'VENDOR_CLOUD'],
                  [
                    'Status',
                    a.status === 'PAID' ? (
                      <Pill key="s" tone="success">
                        Verified
                      </Pill>
                    ) : (
                      <Pill key="s" tone="warning">
                        Verification pending
                      </Pill>
                    ),
                  ],
                  ['Submissions', String(a.paySubmissions)],
                  [
                    'O1 last verified balance',
                    <span key="b">
                      <Money value={s.verified.o1} />{' '}
                      {unknown && (
                        <span className="text-xs text-warning-foreground">
                          stale · refresh pending
                        </span>
                      )}
                    </span>,
                  ],
                  [
                    'Explorer',
                    <span key="x" className="text-muted-foreground">
                      Disabled in simulation
                    </span>,
                  ],
                ] as Array<[string, ReactNode]>
              ).map(([label, value]) => (
                <TableRow key={label}>
                  <TableCell className="text-muted-foreground">
                    {label}
                  </TableCell>
                  <TableCell className="text-right">{value}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <DialogFooter>
            <Button disabled title="Not allowed while the outcome is unknown">
              Retry payment
            </Button>
            <Button onClick={() => setStatus(false)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function Bal({
  label,
  value,
  sub,
  warn,
}: {
  label: string;
  value: bigint;
  sub?: string;
  warn?: boolean;
}) {
  return (
    <div
      className={cn('rounded-md border p-3', warn && 'border-warning-border')}
    >
      <p className="text-muted-foreground">{label}</p>
      <p className="text-lg">
        <Money value={value} />
      </p>
      {sub && (
        <p
          className={cn(
            'text-xs',
            warn ? 'text-warning-foreground' : 'text-subtle-foreground',
          )}
        >
          {sub}
        </p>
      )}
    </div>
  );
}

function EvidenceTab({ s }: { s: ScenarioState }) {
  const [open, setOpen] = useState(false);
  const [receipt, setReceipt] = useState(false);
  const a = s.a;
  const chain: Array<[string, ReactNode, boolean]> = [
    ['Invoice', <span key="i">INV-CLOUD-042 · revision 1</span>, true],
    ['Approval', <Ref key="a">{FX.a.approvalRef}</Ref>, true],
    [
      'Plan',
      <span key="p">
        <Ref>{FX.plan.id}</Ref> · EARLY 980
      </span>,
      true,
    ],
    ['Payment', <Ref key="pm">{FX.refs.payment}</Ref>, a.paySubmissions > 0],
    ['Receipt', <Ref key="r">{FX.refs.pay}</Ref>, a.status === 'PAID'],
    [
      'Reconciliation',
      <span key="rc">
        <Ref>{FX.refs.recon}</Ref> · {a.recon}
      </span>,
      a.recon === 'Matched',
    ],
  ];
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title="Evidence"
          description="One chain from invoice to reconciliation"
          action={
            <Button
              data-testid="payment-evidence"
              variant="primary"
              onClick={() => setOpen(true)}
            >
              View payment evidence
            </Button>
          }
        />
        <CardContent className="grid grid-cols-4 gap-3 text-sm">
          <Bal
            label="T"
            value={s.balances.t}
            sub="Payroll 300 + floor 100 protected"
          />
          <Bal label="O1" value={s.balances.o1} sub="Buffer retained" />
          <Bal label="O2" value={s.balances.o2} />
          <div className="rounded-md border p-3">
            <p className="text-muted-foreground">PAYROLL-017</p>
            <p className="mt-1">
              <Pill tone="info">Scheduled · Reserved</Pill>
            </p>
          </div>
        </CardContent>
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <SheetContent width="lg" aria-describedby={undefined}>
          <div className="border-b p-5">
            <DialogTitle className="flex items-center gap-2">
              Payment evidence{' '}
              <SimBadge>Verification source: SIMULATED</SimBadge>
            </DialogTitle>
            <p className="mt-1 text-sm text-muted-foreground">
              INV-CLOUD-042 · inv-cloud-042
            </p>
          </div>
          <div className="grid gap-5 overflow-y-auto p-5">
            <ol className="grid gap-2">
              {chain.map(([label, value, ok], i) => (
                <li
                  key={label}
                  className="flex items-center gap-3 rounded-md border p-3"
                >
                  <span className="grid size-6 place-items-center rounded-full border text-xs font-semibold">
                    {i + 1}
                  </span>
                  <span className="w-32 font-medium">{label}</span>
                  <span className="flex-1">{value}</span>
                  <Pill tone={ok ? 'success' : 'neutral'}>
                    {ok ? 'Linked' : 'Pending'}
                  </Pill>
                </li>
              ))}
            </ol>
            <section className="rounded-md border">
              <button
                type="button"
                className="flex w-full items-center gap-2 p-3 text-left font-semibold"
                onClick={() => setReceipt((v) => !v)}
              >
                {receipt ? (
                  <ChevronDown className="size-4" aria-hidden="true" />
                ) : (
                  <ChevronRight className="size-4" aria-hidden="true" />
                )}{' '}
                Receipt checks
              </button>
              {receipt && (
                <ul className="grid gap-1.5 border-t p-3">
                  <Check ok={a.status === 'PAID'}>
                    Recipient VENDOR_CLOUD matches approval
                  </Check>
                  <Check ok={a.status === 'PAID'}>
                    Asset USDC (usdc-test) matches
                  </Check>
                  <Check ok={a.status === 'PAID'}>
                    Amount 980 matches selected EARLY term
                  </Check>
                  <Check ok={a.status === 'PAID'}>
                    Confirmation policy met · verification source SIMULATED
                  </Check>
                  <li className="text-xs text-subtle-foreground">
                    Public explorer disabled in simulation. No 0x hash is shown.
                  </li>
                </ul>
              )}
            </section>
            <section className="rounded-md border p-3">
              <h3 className="flex items-center gap-2 font-semibold">
                Reconciliation{' '}
                <Pill tone={a.recon === 'Matched' ? 'success' : 'neutral'}>
                  {a.recon}
                </Pill>{' '}
                <span className="text-xs font-normal text-muted-foreground">
                  by system
                </span>
              </h3>
              <div className="mt-2 max-w-md">
                <Row label="Paid amount" value={FX.a.early} />
                <Row label="Discount captured" value={grossDiscount} />
                <div className="flex justify-between py-1.5">
                  <span className="text-muted-foreground">
                    Estimated net benefit{' '}
                    <span className="block text-xs text-subtle-foreground">
                      Estimate, synthetic assumptions; separate from discount
                    </span>
                  </span>
                  <span className="num font-medium">
                    ≈ {usdRounded(earlyNetEstimate)} USDC
                  </span>
                </div>
              </div>
              <p className="mt-2 text-xs text-subtle-foreground">
                Matched does not mean posted to ERP or confirmed by the vendor.
              </p>
            </section>
          </div>
        </SheetContent>
      </Dialog>
    </div>
  );
}

// ---------------------------------------------------------------- Invoice X (security)

function InvoiceX() {
  const s = useScenario();
  const navigate = useNavigate();
  if (!s.security.loaded)
    return <p className="text-muted-foreground">Invoice not found.</p>;
  return (
    <>
      <Header number={FX.x.number} id={FX.x.id}>
        {s.security.blocked ? (
          <Pill tone="danger">Blocked</Pill>
        ) : (
          <Pill tone="warning">Flagged review</Pill>
        )}
      </Header>
      <div className="grid grid-cols-2 gap-4">
        <Card>
          <CardHeader title="Document" />
          <CardContent className="font-mono text-sm leading-7">
            Invoice INV-CLOUD-043. Amount: 250 USDC. Payment instruction:{' '}
            {FX.x.instruction}
          </CardContent>
        </Card>
        <Card>
          <CardHeader title="Review" description="No approvals yet" />
          <CardContent className="grid gap-3">
            <Row label="Amount" value={FX.x.amount} />
            <Alert tone="danger" title="Recipient not in registry">
              Address instruction differs from the registered vendor address.{' '}
              <Ref>UNKNOWN_RECIPIENT</Ref> is not an approved payee. Mandate
              policy: unknown payee BLOCK.
            </Alert>
            {s.security.blocked ? (
              <Alert
                tone="danger"
                title="BLOCKED_UNKNOWN_RECIPIENT"
                data-testid="security-block"
              >
                Submission rejected before authority is granted. No approval,
                reserve, plan or payment created. Ledger unchanged.
              </Alert>
            ) : (
              <Button
                variant="primary"
                disabled={s.role !== 'FINANCE'}
                onClick={() => dispatch({ type: 'SUBMIT_X' })}
              >
                Submit for approval
              </Button>
            )}
            <Button onClick={() => navigate('/demo/audit')}>
              View security evidence
            </Button>
            <p className="text-sm text-muted-foreground">
              Signed in as {ACTORS[s.role].name} ({ACTORS[s.role].title})
            </p>
          </CardContent>
        </Card>
      </div>
    </>
  );
}

function ScheduledInvoice({ id }: { id: string }) {
  const s = useScenario();
  const inv = id === FX.b.id ? FX.b : FX.c;
  if (id === FX.c.id && !s.cApproved)
    return <p className="text-muted-foreground">Invoice not found.</p>;
  return (
    <>
      <Header number={inv.number} id={inv.id}>
        <Pill tone="info">Approved · Scheduled</Pill>
      </Header>
      <Card>
        <CardContent>
          <Row label="Amount" value={inv.amount} />
          <div className="grid gap-1 py-2 text-sm text-muted-foreground">
            <p>Payee: {inv.payee}</p>
            <p>
              Due {utc(inv.dueAt, false)} · execution window opens at the due
              time · do not pay early
            </p>
            <p>
              Reserved at T · approval <Ref>{inv.approvalRef}</Ref> (separate
              from INV-CLOUD-042)
            </p>
            <p>Not paid in this scenario.</p>
          </div>
        </CardContent>
      </Card>
    </>
  );
}
