import { CheckCircle2, Loader2 } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';

import { KeyValueList } from '@/components/domain/display';
import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge, type Tone } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Checkbox,
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
import { Label } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import { useOrgScope } from '@/features/orgs/org-scope';
import { t } from '@/lib/i18n';

import { actionError, useDemoAction, useScenario } from './api';
import { StaleBadge } from './overview-page';
import { fmt, invoiceLabel, invoiceTone, roleNames, utc } from './format';
import { Usdc } from './usdc';
import { SecurityReportDialog } from './security-report';
import type { ReconStatus, ScenarioView, StepState } from './types';

const stepLabel: Record<StepState, string> = {
  PLANNED: 'Planned',
  SUBMITTED: 'Submitted',
  CONFIRMED: 'Confirmed',
  OUTCOME_UNKNOWN: 'Outcome unknown',
};
const stepTone: Record<StepState, Tone> = {
  PLANNED: 'neutral',
  SUBMITTED: 'info',
  CONFIRMED: 'success',
  OUTCOME_UNKNOWN: 'warning',
};
const reconLabel: Record<ReconStatus, string> = {
  NONE: 'Not started',
  PENDING_VERIFICATION: 'Pending verification',
  MATCHING: 'Matching',
  MATCHED: 'Matched',
};

/* ───────────── Review ───────────── */

function ReviewTab({ data }: { data: ScenarioView }) {
  const { state, fixture } = data;
  const a = state.invoiceA;
  const doc = fixture.documents[0];
  const inv = fixture.invoices[0];
  const payee = fixture.payees[0];
  const [verified, setVerified] = useState(false);
  const [approving, setApproving] = useState(false);
  const submit = useDemoAction<{ verified: boolean }>(
    '/demo/invoices/inv-cloud-042/submit',
  );
  const approve = useDemoAction('/demo/invoices/inv-cloud-042/approve');

  if (a.status === 'EXTRACTING') {
    return (
      <Card>
        <CardContent
          className="flex items-center gap-3 py-8"
          data-testid="invoice-extracting"
        >
          <Loader2
            className="size-5 animate-spin text-primary"
            aria-hidden="true"
          />
          <div>
            <p className="text-base font-medium">{t('Extracting')}</p>
            <p className="text-sm text-muted-foreground">
              {t('Reading {{file}}', { file: doc.fileName })}
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const draft = a.status === 'DRAFT';
  const finance = state.role === 'FINANCE';
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('Source document')} description={doc.fileName} />
          <CardContent>
            <p
              className="whitespace-pre-wrap rounded-md border bg-surface-muted p-3 font-mono text-sm"
              data-testid="invoice-source"
            >
              {doc.sourceText}
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader
            title={t('Extracted fields')}
            action={
              <Badge tone="ai" data-testid="recorded-extraction">
                {t('Recorded extraction')}
              </Badge>
            }
          />
          <CardContent>
            <KeyValueList
              items={[
                { label: t('Invoice number'), value: inv.number },
                { label: t('Vendor'), value: payee.name },
                {
                  label: t('Standard amount'),
                  hint: `${t('Due')} ${utc(inv.dueAt)}`,
                  value: <Usdc value={inv.standardAmount} />,
                },
                {
                  label: t('Early amount'),
                  hint: `${inv.discountBps / 100}% ${t('discount if paid by')} ${utc(inv.earlyDeadline)}`,
                  value: <Usdc value={inv.earlyAmount} />,
                },
                { label: t('Paying wallet'), value: fixture.accounts[1].name },
                { label: t('Asset'), value: 'USDC' },
                {
                  label: t('Payee registry'),
                  value: (
                    <span className="inline-flex items-center gap-1.5">
                      <CheckCircle2
                        className="size-4 text-success"
                        aria-hidden="true"
                      />
                      {t('Match')} ·{' '}
                      {payee.status === 'ACTIVE' ? t('Active') : payee.status}
                    </span>
                  ),
                },
                { label: t('Revision'), value: inv.revision },
                {
                  label: t('Status'),
                  value: (
                    <Badge tone={invoiceTone(a.status)}>
                      {t(invoiceLabel[a.status])}
                    </Badge>
                  ),
                },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      {draft && finance && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <Checkbox
                id="invoice-reviewed"
                data-testid="invoice-reviewed"
                checked={verified}
                onCheckedChange={(value) => setVerified(value === true)}
              />
              <Label htmlFor="invoice-reviewed">
                {t('I verified the invoice fields')}
              </Label>
            </div>
            <Button
              variant="primary"
              data-testid="submit-invoice"
              disabled={!verified}
              loading={submit.isPending}
              onClick={() => submit.mutate({ verified })}
            >
              {t('Submit for approval')}
            </Button>
            {submit.isError && (
              <Alert tone="danger" className="w-full">
                {actionError(submit.error)}
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {draft && !finance && (
        <Alert tone="info">
          {t('Only Finance (Linh) reviews and submits a draft invoice.')}
        </Alert>
      )}

      {a.status === 'AWAITING_APPROVAL' && (
        <Card>
          <CardContent className="flex flex-wrap items-center gap-4">
            <Badge tone="info" data-testid="awaiting-approval">
              {t('Awaiting approval')}
            </Badge>
            {state.role === 'APPROVER' ? (
              <Button
                variant="primary"
                data-testid="review-approve"
                onClick={() => setApproving(true)}
              >
                {t('Review & approve')}
              </Button>
            ) : (
              <p
                className="text-sm text-muted-foreground"
                data-testid="no-self-approval"
              >
                {state.role === 'FINANCE'
                  ? t(
                      'Finance cannot approve its own invoice. Switch to the Approver (An).',
                    )
                  : t('Only the Approver (An) approves this invoice.')}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {a.approvalReference && (
        <Card>
          <CardHeader title={t('Approval')} />
          <CardContent>
            <KeyValueList
              items={[
                {
                  label: t('Approval reference'),
                  value: (
                    <span data-testid="approval-reference">
                      {a.approvalReference}
                    </span>
                  ),
                },
                { label: t('Approved by'), value: 'An · Approver' },
                {
                  label: t('Signature'),
                  value: (
                    <Badge tone="warning">{t('Simulated signature')}</Badge>
                  ),
                },
                {
                  label: t('Plan'),
                  value: (
                    <span data-testid="plan-status">
                      {a.planReady ? t(planStatusLabel(data)) : t('Planning…')}
                    </span>
                  ),
                },
              ]}
            />
          </CardContent>
        </Card>
      )}

      <Dialog open={approving} onOpenChange={setApproving}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Review & approve')}</DialogTitle>
            <DialogDescription>
              {t('Check what you are approving. This is a demo approval.')}
            </DialogDescription>
          </DialogHeader>
          <KeyValueList
            items={[
              {
                label: t('Invoice'),
                value: `${inv.number} · revision ${inv.revision}`,
              },
              {
                label: t('Standard amount'),
                value: <Usdc value={inv.standardAmount} />,
              },
              {
                label: t('Early amount'),
                value: <Usdc value={inv.earlyAmount} />,
              },
              { label: t('Recipient'), value: payee.name },
              { label: t('Paying wallet'), value: fixture.accounts[1].name },
              { label: t('Token'), value: 'USDC (synthetic)' },
              { label: t('Early deadline'), value: utc(inv.earlyDeadline) },
              { label: t('Due'), value: utc(inv.dueAt) },
              {
                label: t('Approval expires'),
                value: utc(inv.approvalExpiresAt),
              },
              {
                label: t('Signature'),
                value: <Badge tone="warning">{t('Simulated signature')}</Badge>,
              },
            ]}
          />
          {approve.isError && (
            <Alert tone="danger">{actionError(approve.error)}</Alert>
          )}
          <DialogFooter>
            <Button variant="secondary" onClick={() => setApproving(false)}>
              {t('Cancel')}
            </Button>
            <Button
              variant="primary"
              data-testid="approval-confirm"
              loading={approve.isPending}
              onClick={() =>
                approve.mutate(undefined, {
                  onSuccess: () => setApproving(false),
                })
              }
            >
              {t('Confirm demo approval')}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function planStatusLabel(data: ScenarioView): string {
  const a = data.state.invoiceA;
  if (a.status === 'READY_WAITING_WINDOW')
    return 'Ready - waiting for approved window';
  if (a.status === 'PAID') return 'Completed';
  if (a.status === 'OUTCOME_UNKNOWN') return 'Executing - verifying payment';
  return 'Executing';
}

/* ───────────── Plan ───────────── */

function PlanTab({ data }: { data: ScenarioView }) {
  const { state, fixture } = data;
  const [funding, setFunding] = useState(false);
  const inv = fixture.invoices[0];
  const plan = fixture.paymentPlan;
  const a = state.invoiceA;
  if (!a.planReady) {
    return (
      <Alert tone="info">
        {a.status === 'APPROVED'
          ? t('Planning…')
          : t('There is no plan until the invoice is approved.')}
      </Alert>
    );
  }
  const e = data.economics;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title={`${t('Plan')} ${plan.id}`}
          action={<Badge tone="info">{t(planStatusLabel(data))}</Badge>}
        />
        <CardContent>
          <KeyValueList
            items={[
              {
                label: t('Selected'),
                value: <Badge tone="success">{plan.selectedTerm}</Badge>,
              },
              {
                label: t('Source'),
                value: (
                  <Badge tone="neutral" data-testid="plan-source">
                    {t('Deterministic scenario model')}
                  </Badge>
                ),
              },
              { label: t('Approval'), value: plan.approvalReference },
            ]}
          />
        </CardContent>
      </Card>

      <Card data-testid="plan-alternatives">
        <CardHeader title={t('Compare options')} />
        <CardContent className="grid gap-2">
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="font-medium">{t('Standard')}</p>
              <p className="text-sm text-muted-foreground">
                {t('Pay on the due date')} · D+7 ({utc(inv.dueAt)})
              </p>
            </div>
            <Usdc value={e.standard} />
          </div>
          <div className="flex items-center justify-between rounded-md border border-success-border bg-success-muted p-3">
            <div>
              <p className="font-medium">
                {t('Early')} <Badge tone="success">{t('Selected')}</Badge>
              </p>
              <p className="text-sm text-muted-foreground">
                {t('Pay by')} {utc(inv.earlyDeadline)}
              </p>
            </div>
            <Usdc value={e.early} />
          </div>
          <div className="flex items-center justify-between rounded-md border p-3">
            <div>
              <p className="font-medium">
                {t('Borrow proposal')}{' '}
                <Badge tone="neutral">{t('Not selected')}</Badge>
              </p>
              <p className="text-sm text-muted-foreground">
                {t('Requires separate authorization')}
              </p>
            </div>
            <span className="text-sm text-muted-foreground">—</span>
          </div>
        </CardContent>
      </Card>

      <Card data-testid="estimated-benefit">
        <CardHeader
          title={t('Estimated benefit')}
          action={<Badge tone="warning">{t('Synthetic assumptions')}</Badge>}
        />
        <CardContent>
          <KeyValueList
            items={[
              {
                label: t('Discount'),
                value: <Usdc value={e.discount} fixed />,
              },
              {
                label: t('Cash cost'),
                value: <Usdc value={e.cashCost} approx fixed />,
              },
              {
                label: t('Fee allowance'),
                value: <Usdc value={e.feeAllowance} fixed />,
              },
              {
                label: t('Estimated net benefit'),
                value: (
                  <span data-testid="estimated-net">
                    <Usdc value={e.net} approx fixed />
                  </span>
                ),
              },
            ]}
          />
          <p className="mt-3 text-sm text-muted-foreground">
            {t(
              'An estimate under synthetic assumptions, not a realized result.',
            )}{' '}
            {t('Source')}: {t('Deterministic scenario model')}.
          </p>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('Funding')}
          action={
            <Button size="sm" onClick={() => setFunding(true)}>
              {t('View funding breakdown')}
            </Button>
          }
        />
        <CardContent>
          <ol className="grid gap-2" data-testid="plan-steps">
            {plan.steps.map((step, index) => {
              const status =
                state.invoiceA.steps[
                  step.id as keyof typeof state.invoiceA.steps
                ]?.status ?? 'PLANNED';
              return (
                <li
                  key={step.id}
                  className="flex items-center justify-between gap-3 rounded-md border p-3"
                >
                  <span>
                    <span className="num mr-2 text-muted-foreground">
                      {index + 1}.
                    </span>
                    <span className="font-medium">{step.action}</span>{' '}
                    <span className="text-muted-foreground">
                      {stepRoute(step.from, step.to)}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    <Usdc value={step.amount} />
                    <Badge tone={stepTone[status]}>
                      {t(stepLabel[status])}
                    </Badge>
                  </span>
                </li>
              );
            })}
          </ol>
          {a.status === 'READY_WAITING_WINDOW' && (
            <p className="mt-3 text-sm text-muted-foreground">
              {t(
                'No action has been executed yet. The agent starts when the approved window opens.',
              )}
            </p>
          )}
        </CardContent>
      </Card>

      <Dialog open={funding} onOpenChange={setFunding}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Funding breakdown')}</DialogTitle>
            <DialogDescription>
              {t('Why the plan withdraws from Aave first')}
            </DialogDescription>
          </DialogHeader>
          <div data-testid="liquidity-shortage">
            <KeyValueList
              items={[
                {
                  label: t('O1 needs'),
                  hint: t('early amount + buffer - O1 balance at day start'),
                  value: <Usdc value={data.funding.o1Need} />,
                },
                {
                  label: t('T funding capacity for A'),
                  hint: t(
                    'capacity for this invoice, excluding other obligations',
                  ),
                  value: <Usdc value={data.funding.tCapacity} />,
                },
                {
                  label: t('Deficit'),
                  value: <Usdc value={data.funding.gap} />,
                },
                {
                  label: t('Withdraw margin'),
                  value: `${data.funding.marginBps / 100}%`,
                },
                {
                  label: t('Withdraw from Aave'),
                  value: <Usdc value={data.funding.withdraw} />,
                },
              ]}
            />
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

const alias: Record<string, string> = {
  'pool-aave-test': 'Aave',
  'safe-t': 'T',
  'safe-o1': 'O1',
  'payee-cloud': 'Northstar Cloud Vendor',
};
const stepRoute = (from: string, to: string) =>
  `${alias[from] ?? from} → ${alias[to] ?? to}`;

/* ───────────── Execution ───────────── */

const PREFLIGHT = [
  'Approval valid',
  'Payee active',
  'Policy within mandate',
  'Balance snapshot fresh',
  'Pool enabled and healthy',
  'Gas sufficient',
];

function ExecutionTab({ data }: { data: ScenarioView }) {
  const { state, fixture } = data;
  const a = state.invoiceA;
  const [txOpen, setTxOpen] = useState(false);
  const plan = fixture.paymentPlan;
  if (!state.director.windowReleased) {
    return (
      <Alert tone="info" data-testid="execution-timeline">
        {t('Waiting for the approved window')} (
        {utc(fixture.clock.executionWindowOpensAt)}).{' '}
        {t(
          'There is no manual run: the agent starts by itself when the window opens.',
        )}
      </Alert>
    );
  }
  const unknown = a.status === 'OUTCOME_UNKNOWN';
  const references: Record<string, string> = {
    'step-withdraw-001': fixture.mockEvidence.withdrawReference,
    'step-refill-001': fixture.mockEvidence.refillReference,
    'step-pay-001': fixture.mockEvidence.payReference,
  };
  return (
    <div className="grid gap-4" data-testid="execution-timeline">
      <Card>
        <CardHeader
          title={t('Preflight checks')}
          action={
            a.execution === 'PREFLIGHT' ? (
              <Badge tone="info">{t('Checking')}</Badge>
            ) : (
              <Badge tone="success">{t('All pass')}</Badge>
            )
          }
        />
        <CardContent>
          <ul className="grid gap-1 sm:grid-cols-2">
            {PREFLIGHT.map((name) => (
              <li key={name} className="flex items-center gap-2 text-base">
                {a.execution === 'PREFLIGHT' ? (
                  <Loader2
                    className="size-4 animate-spin text-muted-foreground"
                    aria-hidden="true"
                  />
                ) : (
                  <CheckCircle2
                    className="size-4 text-success"
                    aria-hidden="true"
                  />
                )}
                {t(name)}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={t('Execution timeline')}
          description={`${t('Execution')}: ${executionLabel(a.execution)}`}
        />
        <CardContent>
          <ol className="grid gap-2">
            {plan.steps.map((step) => {
              const s = a.steps[step.id as keyof typeof a.steps];
              const isPay = step.action === 'PAY';
              return (
                <li
                  key={step.id}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3"
                  data-testid={`step-${step.action.toLowerCase()}`}
                >
                  <span>
                    <span className="font-medium">{step.action}</span>{' '}
                    <span className="text-muted-foreground">
                      {stepRoute(step.from, step.to)}
                    </span>
                    {s.reference && (
                      <span className="num ml-2 text-sm text-muted-foreground">
                        {s.reference}
                      </span>
                    )}
                  </span>
                  <span className="flex items-center gap-2">
                    <Usdc value={step.amount} />
                    <Badge
                      tone={stepTone[s.status]}
                      data-testid={
                        isPay && s.status === 'OUTCOME_UNKNOWN'
                          ? 'pay-outcome-unknown'
                          : undefined
                      }
                    >
                      {t(stepLabel[s.status])}
                    </Badge>
                    {isPay &&
                      s.status !== 'PLANNED' &&
                      s.status !== 'SUBMITTED' && (
                        <Button size="sm" onClick={() => setTxOpen(true)}>
                          {t('View transaction status')}
                        </Button>
                      )}
                  </span>
                </li>
              );
            })}
          </ol>
        </CardContent>
      </Card>

      {unknown && (
        <Alert tone="warning" title={t('Outcome unknown')}>
          {t(
            'The network did not acknowledge the payment. The same transaction is being verified; it is not sent again.',
          )}{' '}
          <span className="num">{fixture.mockEvidence.payReference}</span>
          <div className="mt-1 flex items-center gap-2">
            <StaleBadge />
            <span>
              {t('Last verified balance')}: O1 {fmt(state.ledger.o1)} · T{' '}
              {fmt(state.ledger.t)} USDC
            </span>
          </div>
        </Alert>
      )}

      <Card>
        <CardHeader title={t('Result')} />
        <CardContent>
          <KeyValueList
            items={[
              {
                label: t('Invoice status'),
                value: (
                  <Badge
                    tone={invoiceTone(a.status)}
                    data-testid="invoice-status"
                  >
                    {t(invoiceLabel[a.status])}
                  </Badge>
                ),
              },
              {
                label: t('Payments submitted'),
                value: (
                  <span data-testid="payment-count">{a.paymentCount}</span>
                ),
                hint: `${t('Submissions')}: ${a.paySubmissions}`,
              },
              {
                label: t('Reconciliation'),
                value: (
                  <Badge
                    tone={
                      a.recon === 'MATCHED'
                        ? 'success'
                        : a.recon === 'NONE'
                          ? 'neutral'
                          : 'info'
                    }
                    data-testid="recon-status"
                  >
                    {t(reconLabel[a.recon])}
                  </Badge>
                ),
              },
            ]}
          />
        </CardContent>
      </Card>

      <Dialog open={txOpen} onOpenChange={setTxOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Transaction status')}</DialogTitle>
            <DialogDescription>
              {t('PAY from O1 to the vendor')}
            </DialogDescription>
          </DialogHeader>
          <div data-testid="tx-status">
            <KeyValueList
              items={[
                {
                  label: t('Reference'),
                  value: (
                    <span className="num">{references['step-pay-001']}</span>
                  ),
                },
                {
                  label: t('Status'),
                  value: unknown ? (
                    <Badge tone="warning">{t('Verification pending')}</Badge>
                  ) : (
                    <Badge tone="success">{t('Verified')}</Badge>
                  ),
                },
                { label: t('Payments submitted'), value: a.paySubmissions },
                {
                  label: t('Last verified balance'),
                  value: unknown ? (
                    <span className="inline-flex items-center gap-2">
                      O1 {fmt(state.ledger.o1)} · T {fmt(state.ledger.t)} USDC{' '}
                      <StaleBadge />
                    </span>
                  ) : (
                    <span>
                      O1 {fmt(state.ledger.o1)} · T {fmt(state.ledger.t)} USDC
                    </span>
                  ),
                },
              ]}
            />
          </div>
          {unknown && (
            <p className="text-sm text-muted-foreground">
              {t(
                'No retry is offered while the outcome is unknown. The existing transaction is verified instead.',
              )}
            </p>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

const executionLabel = (status: string) =>
  ({
    NOT_STARTED: 'Not started',
    PREFLIGHT: 'Preflight',
    RUNNING: 'Running',
    OUTCOME_UNKNOWN: 'Outcome unknown',
    COMPLETED: 'Completed',
  })[status] ?? status;

/* ───────────── Evidence ───────────── */

function EvidenceTab({ data }: { data: ScenarioView }) {
  const { state, fixture } = data;
  const a = state.invoiceA;
  const [open, setOpen] = useState(false);
  const paid = a.status === 'PAID';
  const inv = fixture.invoices[0];
  const ev = fixture.mockEvidence;
  const chain: Array<[string, ReactNode]> = [
    [t('Invoice'), `${inv.number} (revision ${inv.revision})`],
    [t('Approval'), a.approvalReference ?? '—'],
    [t('Plan'), fixture.paymentPlan.id],
    [t('Payment'), ev.paymentId],
    [t('Transaction'), ev.payReference],
    [
      t('Receipt'),
      paid ? t('Verified (simulated)') : t('Pending verification'),
    ],
    [t('Reconciliation'), `${ev.reconciliationId} · ${t(reconLabel[a.recon])}`],
  ];
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title={t('Payment evidence')}
          action={
            <Button size="sm" disabled={!paid} onClick={() => setOpen(true)}>
              {t('View payment evidence')}
            </Button>
          }
        />
        <CardContent>
          <p className="text-sm text-muted-foreground">
            {paid
              ? t(
                  'The payment is verified and reconciled. Open the evidence to see each check.',
                )
              : t('Evidence appears after the payment is verified.')}
          </p>
        </CardContent>
      </Card>
      <Dialog open={open} onOpenChange={setOpen}>
        <SheetContent width="lg" aria-describedby={undefined}>
          <div className="border-b p-4 pr-12">
            <DialogTitle className="text-lg font-semibold">
              {t('Payment evidence')}
            </DialogTitle>
          </div>
          <div
            className="grid gap-5 overflow-y-auto p-4"
            data-testid="payment-evidence"
          >
            <section>
              <h3 className="mb-2 text-base font-semibold">
                {t('Evidence chain')}
              </h3>
              <KeyValueList
                items={chain.map(([label, value]) => ({
                  label,
                  value: <span className="num">{value}</span>,
                }))}
              />
            </section>
            <section>
              <h3 className="mb-2 text-base font-semibold">
                {t('Receipt checks')}
              </h3>
              <KeyValueList
                items={[
                  {
                    label: t('Recipient'),
                    value: <Badge tone="success">{t('Match')}</Badge>,
                  },
                  {
                    label: t('Asset'),
                    value: <Badge tone="success">{t('Match')}</Badge>,
                  },
                  {
                    label: t('Amount'),
                    value: (
                      <span className="inline-flex items-center gap-2">
                        <Usdc value={inv.earlyAmount} />
                        <Badge tone="success">{t('Match')}</Badge>
                      </span>
                    ),
                  },
                  {
                    label: t('Verification source'),
                    value: <Badge tone="warning">SIMULATED</Badge>,
                  },
                ]}
              />
              <p className="mt-2 text-sm text-muted-foreground">
                {t('No block explorer links: this is not a public chain.')}
              </p>
            </section>
            <section>
              <h3 className="mb-2 text-base font-semibold">
                {t('Reconciliation')}
              </h3>
              <KeyValueList
                items={[
                  {
                    label: t('Status'),
                    hint: t('Set by the system'),
                    value: (
                      <Badge tone="success">{t(reconLabel[a.recon])}</Badge>
                    ),
                  },
                  {
                    label: t('Paid'),
                    value: <Usdc value={state.ledger.vendorPaid} />,
                  },
                  {
                    label: t('Discount'),
                    value: <Usdc value={data.economics.discount} fixed />,
                  },
                  {
                    label: t('Estimated net benefit'),
                    hint: t(
                      'Estimate under synthetic assumptions, kept apart from the discount',
                    ),
                    value: <Usdc value={data.economics.net} approx fixed />,
                  },
                ]}
              />
            </section>
            <section>
              <h3 className="mb-2 text-base font-semibold">
                {t('Balance summary')} ({data.stage})
              </h3>
              <KeyValueList
                items={[
                  { label: 'T', value: <Usdc value={data.t.balance} /> },
                  { label: 'O1', value: <Usdc value={data.o1.balance} /> },
                  {
                    label: t('Payroll B'),
                    value: <Badge tone="neutral">{t('Reserved')}</Badge>,
                  },
                ]}
              />
            </section>
          </div>
        </SheetContent>
      </Dialog>
    </div>
  );
}

/* ───────────── Security invoice X ───────────── */

function SecurityInvoice({ data }: { data: ScenarioView }) {
  const { state, fixture } = data;
  const x = fixture.securityScenario;
  const submit = useDemoAction('/demo/invoices/inv-security-043/submit');
  const [report, setReport] = useState(false);
  const blocked = state.invoiceX.status === 'BLOCKED_UNKNOWN_RECIPIENT';
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader
          title={t('Invoice')}
          action={
            blocked ? (
              <Badge tone="danger">BLOCKED_UNKNOWN_RECIPIENT</Badge>
            ) : (
              <Badge tone="warning">{t('Flagged review')}</Badge>
            )
          }
        />
        <CardContent>
          <KeyValueList
            items={[
              { label: t('Invoice number'), value: x.number },
              { label: t('Amount'), value: <Usdc value={x.amount} /> },
              {
                label: t('Recipient'),
                value: (
                  <span className="inline-flex items-center gap-2">
                    {x.recipientAlias}{' '}
                    <Badge tone="danger">{t('Unknown recipient')}</Badge>
                  </span>
                ),
              },
              { label: t('Instruction'), value: x.instruction },
              { label: t('Approvals'), value: state.invoiceX.approvals },
            ]}
          />
        </CardContent>
      </Card>
      {!blocked && state.role === 'FINANCE' && (
        <div className="flex items-center gap-3">
          <Button
            variant="primary"
            data-testid="submit-invoice"
            loading={submit.isPending}
            onClick={() => submit.mutate()}
          >
            {t('Submit for approval')}
          </Button>
          {submit.isError && (
            <Alert tone="danger">{actionError(submit.error)}</Alert>
          )}
        </div>
      )}
      {!blocked && state.role !== 'FINANCE' && (
        <Alert tone="info">
          {t('Only Finance (Linh) submits this invoice.')}
        </Alert>
      )}
      {blocked && (
        <Alert
          tone="danger"
          title="BLOCKED_UNKNOWN_RECIPIENT"
          data-testid="security-block"
        >
          <p>
            {t(
              'The recipient is not in the payee registry, so the app stopped the invoice before any approval.',
            )}
          </p>
          <ul className="mt-2 list-disc pl-5">
            <li>
              {t('Approvals')}: {state.invoiceX.approvals}
            </li>
            <li>
              {t('Reserves')}: {state.invoiceX.reserves}
            </li>
            <li>
              {t('Plans')}: {state.invoiceX.plans}
            </li>
            <li>
              {t('Payments / broadcasts')}: {state.invoiceX.payments}
            </li>
            <li>
              {t('Main ledger')} ({data.stage}): T {fmt(state.ledger.t)} · O1{' '}
              {fmt(state.ledger.o1)} · Aave {fmt(state.ledger.aave)} USDC{' '}
              {t('unchanged')}
            </li>
          </ul>
          <div className="mt-3">
            <Button size="sm" onClick={() => setReport(true)}>
              {t('View security evidence')}
            </Button>
          </div>
        </Alert>
      )}
      <SecurityReportDialog
        data={data}
        open={report}
        onOpenChange={setReport}
      />
    </div>
  );
}

/* ───────────── Page ───────────── */

function ObligationDetail({ data, id }: { data: ScenarioView; id: string }) {
  const inv = data.fixture.invoices.find((item) => item.id === id);
  if (!inv || !('amount' in inv)) return null;
  return (
    <Card>
      <CardHeader
        title={inv.number}
        action={<Badge tone="info">{t('Approved / Scheduled')}</Badge>}
      />
      <CardContent>
        <KeyValueList
          items={[
            { label: t('Amount'), value: <Usdc value={inv.amount} /> },
            { label: t('Due'), value: utc(inv.dueAt) },
            { label: t('Approval reference'), value: inv.approvalReference },
            { label: t('Reserve'), value: t('Held at T until paid') },
            { label: t('Early payment'), value: t('Never: do not pay early') },
          ]}
        />
      </CardContent>
    </Card>
  );
}

export function DemoInvoiceDetailPage() {
  const { r } = useParams();
  const scope = useOrgScope();
  const { data } = useScenario();
  const [tab, setTab] = useState('review');
  if (!data) {
    return (
      <Page title={t('Invoice')}>
        <ListSkeleton />
      </Page>
    );
  }
  const { state, fixture } = data;
  const crumbs = [
    { label: t('Invoices'), to: `${scope.base}/requests` },
    { label: r ?? '' },
  ];
  const known = fixture.invoices.some((item) => item.id === r);
  const isA =
    r === fixture.invoices[0].id && state.invoiceA.status !== 'ABSENT';
  const isX =
    r === fixture.securityScenario.invoiceId && state.invoiceX.present;
  const isOther = known && r !== fixture.invoices[0].id;

  if (!isA && !isX && !isOther) {
    return (
      <Page title={t('Invoice')} crumbs={crumbs}>
        <Alert tone="info">{t('This invoice does not exist yet.')}</Alert>
      </Page>
    );
  }
  if (isX) {
    return (
      <Page
        title={fixture.securityScenario.number}
        crumbs={crumbs}
        description={`${t('Request ID')} ${fixture.securityScenario.invoiceId}`}
      >
        <SecurityInvoice data={data} />
      </Page>
    );
  }
  if (isOther) {
    const inv = fixture.invoices.find((item) => item.id === r)!;
    return (
      <Page
        title={inv.number}
        crumbs={crumbs}
        description={`${t('Request ID')} ${inv.id}`}
      >
        <ObligationDetail data={data} id={inv.id} />
      </Page>
    );
  }
  const a = state.invoiceA;
  return (
    <Page
      title={fixture.invoices[0].number}
      crumbs={crumbs}
      description={`${fixture.payees[0].name} · ${t('Request ID')} ${fixture.invoices[0].id} · ${t('Created by')} ${roleNames.FINANCE.name}`}
      titleSlot={
        <Badge tone={invoiceTone(a.status)} data-testid="invoice-header-status">
          {t(invoiceLabel[a.status])}
        </Badge>
      }
    >
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4">
          <TabsTrigger value="review">{t('Review')}</TabsTrigger>
          <TabsTrigger value="plan">{t('Plan')}</TabsTrigger>
          <TabsTrigger value="execution">{t('Execution')}</TabsTrigger>
          <TabsTrigger value="evidence">{t('Evidence')}</TabsTrigger>
        </TabsList>
        <TabsContent value="review">
          <ReviewTab data={data} />
        </TabsContent>
        <TabsContent value="plan">
          <PlanTab data={data} />
        </TabsContent>
        <TabsContent value="execution">
          <ExecutionTab data={data} />
        </TabsContent>
        <TabsContent value="evidence">
          <EvidenceTab data={data} />
        </TabsContent>
      </Tabs>
    </Page>
  );
}
