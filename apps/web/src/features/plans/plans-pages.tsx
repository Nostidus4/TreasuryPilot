import type { ColumnDef } from '@tanstack/react-table';
import {
  ArrowDownToLine,
  ArrowLeftRight,
  ArrowRight,
  ArrowUpFromLine,
  Banknote,
  Bot,
  Check,
  CircleDashed,
  ListOrdered,
  Play,
  RefreshCw,
  Workflow,
  X,
} from 'lucide-react';
import { useMemo } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { DataTable } from '@/components/data-table';
import { Amount, AmountHeader } from '@/components/domain/amount';
import { Address, TxHash } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import {
  AiExplanation,
  PolicyDecision,
  StatusBadge,
} from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert } from '@/components/ui/misc';
import { usePlan, usePlans, useRunNow } from '@/features/operations/api';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { errorMessage } from '@/lib/api/http';
import type { Plan, PlanDetail, PlanStep } from '@/lib/api/types';
import {
  formatDateTime,
  formatRelative,
  formatTime,
  shortHash,
} from '@/lib/format';
import { t } from '@/lib/i18n';
import { planStatus, stepStatus } from '@/lib/status';
import { cn } from '@/lib/utils';

function PlannerBadge({ source }: { source: Plan['plannerSource'] }) {
  return source === 'AI' ? (
    <Badge tone="ai">
      <Bot aria-hidden="true" />
      {t('AI planner')}
    </Badge>
  ) : source === 'RULE_BASED' ? (
    <Badge tone="outline">
      <ListOrdered aria-hidden="true" />
      {t('Rule-based')}
    </Badge>
  ) : (
    <Badge tone="outline">{t('Planner unavailable')}</Badge>
  );
}

export function PlansPage() {
  const scope = useTreasuryScope();
  const navigate = useNavigate();
  const query = usePlans(scope.orgId, scope.treasuryId);

  const columns = useMemo<Array<ColumnDef<Plan, unknown>>>(
    () => [
      {
        id: 'plan',
        header: t('Plan'),
        accessorKey: 'id',
        cell: ({ row }) => (
          <div>
            <p className="num font-medium">{row.original.id}</p>
            <p className="text-xs text-muted-foreground">
              {row.original.plannerSource === 'UNKNOWN'
                ? t('Signed {{when}}', {
                    when: formatDateTime(row.original.createdAt),
                  })
                : formatDateTime(row.original.createdAt)}
            </p>
          </div>
        ),
      },
      {
        id: 'status',
        header: t('Status'),
        accessorKey: 'status',
        cell: ({ row }) => (
          <StatusBadge meta={planStatus(row.original.status)} />
        ),
      },
      {
        id: 'source',
        header: t('Planner'),
        accessorKey: 'plannerSource',
        meta: { hideOnMobile: true },
        cell: ({ row }) => <PlannerBadge source={row.original.plannerSource} />,
      },
      {
        id: 'steps',
        header: t('Steps'),
        accessorKey: 'stepCount',
        meta: { align: 'right', hideOnMobile: true },
        cell: ({ row }) => (
          <span className="num">{row.original.stepCount}</span>
        ),
      },
      {
        id: 'total',
        header: () => <AmountHeader label="Total" />,
        accessorFn: (row) =>
          row.totalAmount
            ? Number(BigInt(row.totalAmount) / 10000n)
            : undefined,
        meta: { align: 'right' },
        cell: ({ row }) =>
          row.original.totalAmount ? (
            <Amount value={row.original.totalAmount} context="column" />
          ) : (
            <span className="text-subtle-foreground">—</span>
          ),
      },
      {
        id: 'saving',
        header: t('Expected saving'),
        accessorFn: (row) =>
          row.expectedSaving
            ? Number(BigInt(row.expectedSaving) / 10000n)
            : undefined,
        meta: { align: 'right', hideOnMobile: true },
        cell: ({ row }) =>
          !row.original.expectedSaving ||
          row.original.expectedSaving === '0' ? (
            <span className="text-subtle-foreground">—</span>
          ) : (
            <Amount value={row.original.expectedSaving} context="column" />
          ),
      },
    ],
    [],
  );

  return (
    <Page
      width="wide"
      title={t('Plans')}
      description={t(
        'A plan is the agent’s proposal for what to pay and refill, in which order. The policy engine validates every plan before a single transaction is sent.',
      )}
    >
      <Card className="overflow-hidden">
        <QueryBoundary query={query}>
          {({ items }) => (
            <DataTable
              columns={columns}
              data={items}
              getRowId={(row) => row.id}
              rowLabel={(row) => t('Open plan {{id}}', { id: row.id })}
              onRowClick={(row) => navigate(`${scope.tBase}/plans/${row.id}`)}
              empty={
                <EmptyState
                  icon={Workflow}
                  title={t('No plans yet')}
                  description={t(
                    'The agent proposes a plan when there are approved requests to pay. Approve a request to see the first one.',
                  )}
                  action={
                    <Button asChild variant="primary">
                      <Link to={`${scope.base}/approvals`}>
                        {t('Open approvals')}
                      </Link>
                    </Button>
                  }
                />
              }
            />
          )}
        </QueryBoundary>
      </Card>
    </Page>
  );
}

const kindMeta = {
  REFILL: { label: 'Refill', icon: RefreshCw },
  PAY: { label: 'Pay', icon: Banknote },
  SUPPLY: { label: 'Supply', icon: ArrowUpFromLine },
  WITHDRAW: { label: 'Withdraw', icon: ArrowDownToLine },
  SWAP: { label: 'Swap', icon: ArrowLeftRight },
} as const;

function StepMarker({ step }: { step: PlanStep }) {
  const meta = stepStatus(step.status, step.confirmations);
  const settled = step.status === 'Verified' || step.status === 'Final';
  const failed = step.status === 'Failed';
  return (
    <span
      className={cn(
        'relative z-10 grid size-7 shrink-0 place-items-center rounded-full border bg-surface text-xs font-medium',
        settled && 'border-success bg-success text-white',
        failed && 'border-danger bg-danger text-white',
        meta.live && 'border-info text-info-foreground',
        step.status === 'Unknown' && 'border-warning text-warning-foreground',
      )}
    >
      {settled ? (
        <Check className="size-4" aria-hidden="true" />
      ) : failed ? (
        <X className="size-4" aria-hidden="true" />
      ) : meta.live ? (
        <CircleDashed className="size-4 animate-spin" aria-hidden="true" />
      ) : (
        <span className="num">{step.index}</span>
      )}
    </span>
  );
}

/**
 * Plan steps as a live timeline (WEB-011 + WEB-012). Status wording comes from
 * lib/status; "Unknown" is shown as still being checked, never as failed.
 */
function StepTimeline({ plan }: { plan: PlanDetail }) {
  const scope = useTreasuryScope();
  return (
    <ol
      className="relative grid gap-0"
      aria-label={t('Execution steps')}
      aria-live="polite"
    >
      {plan.steps.map((step, index) => {
        const kind = kindMeta[step.kind];
        const KindIcon = kind.icon;
        const last = index === plan.steps.length - 1;
        return (
          <li key={step.id} className="relative flex gap-3 pb-5 last:pb-0">
            {!last && (
              <span
                aria-hidden="true"
                className="absolute bottom-0 left-3.5 top-7 w-px bg-border"
              />
            )}
            <StepMarker step={step} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-base font-medium">
                    <KindIcon
                      className="size-4 text-muted-foreground"
                      aria-hidden="true"
                    />
                    {step.title}
                    {step.option === 'EARLY' && (
                      <Badge tone="info">{t('Early payment')}</Badge>
                    )}
                  </p>
                  <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
                    {step.from}
                    <ArrowRight className="size-3" aria-hidden="true" />
                    {step.to}
                    {step.requestId && (
                      <Link
                        to={`${scope.base}/requests/${step.requestId}`}
                        className="text-primary hover:underline"
                      >
                        {t('request')}
                      </Link>
                    )}
                  </p>
                </div>
                {step.amount !== null ? (
                  <Amount value={step.amount} />
                ) : (
                  <span className="text-sm text-subtle-foreground">—</span>
                )}
              </div>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {step.reason}
              </p>
              <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1">
                <StatusBadge
                  meta={stepStatus(step.status, step.confirmations)}
                />
                {step.txHash && <TxHash hash={step.txHash} />}
                {step.verification && (
                  <span
                    className={cn(
                      'text-xs',
                      step.verification === 'VERIFIED'
                        ? 'text-success-foreground'
                        : 'text-danger-foreground',
                    )}
                  >
                    {step.verification === 'VERIFIED'
                      ? t(verificationMessage(step.kind, true))
                      : t(verificationMessage(step.kind, false))}
                  </span>
                )}
                {step.status !== 'Planned' && (
                  <span className="num text-xs text-subtle-foreground">
                    {formatTime(step.updatedAt)}
                  </span>
                )}
              </div>
              {step.status === 'Unknown' && (
                <Alert tone="warning" className="mt-2">
                  {t(
                    'The transaction was sent but no receipt has been seen yet. It may still confirm. Nothing is re-sent while its outcome is unknown.',
                  )}{' '}
                  <Link
                    className="font-medium underline"
                    to={`${scope.base}/review`}
                  >
                    {t('Open review')}
                  </Link>
                </Alert>
              )}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function verificationMessage(kind: PlanStep['kind'], matched: boolean): string {
  if (kind === 'PAY') {
    return matched
      ? 'Payment event matches request, payer, recipient, and amount'
      : 'Payment event is ambiguous, has the wrong event kind, or does not match request, payer, recipient, and amount';
  }
  if (kind === 'REFILL') {
    return matched
      ? 'Refill event matches request, destination, and amount'
      : 'Refill event is ambiguous, has the wrong event kind, or does not match request, destination, and amount';
  }
  return 'Liquidity event is ambiguous, has the wrong event kind, or has a different amount';
}

export function PlanDetailPage() {
  const scope = useTreasuryScope();
  const { p: planId = '' } = useParams();
  const query = usePlan(scope.orgId, planId, scope.live);
  const runNow = useRunNow(scope.orgId, scope.treasuryId);
  const plan = query.data;
  const done = plan?.steps.filter(
    (step) => step.verification === 'VERIFIED',
  ).length;

  return (
    <Page
      width="wide"
      crumbs={[
        { label: t('Plans'), to: `${scope.tBase}/plans` },
        { label: planId },
      ]}
      title={t('Plan {{id}}', { id: planId })}
      titleSlot={
        plan && (
          <>
            <StatusBadge meta={planStatus(plan.status)} />
            <PlannerBadge source={plan.plannerSource} />
          </>
        )
      }
      description={
        plan &&
        t(
          plan.plannerSource === 'UNKNOWN'
            ? 'Signed {{when}} · live updates {{state}}'
            : 'Proposed {{when}} · live updates {{state}}',
          {
            when: formatRelative(plan.createdAt),
            state: scope.live ? t('on') : t('off, refreshing every 2 seconds'),
          },
        )
      }
      actions={
        plan?.status === 'Validated' &&
        scope.can('OPR') && (
          <Button
            variant="primary"
            loading={runNow.isPending}
            onClick={() =>
              runNow.mutate(undefined, {
                onSuccess: () => toast.success(t('Execution started')),
                onError: (error) => toast.error(errorMessage(error)),
              })
            }
          >
            <Play aria-hidden="true" />
            {t('Run now')}
          </Button>
        )
      }
    >
      <QueryBoundary query={query}>
        {(data) => (
          <div className="grid items-start gap-4 lg:grid-cols-5">
            <div className="grid gap-4 lg:col-span-3">
              <Card>
                <CardContent className="grid gap-4 sm:grid-cols-3">
                  <div>
                    <p className="text-sm text-muted-foreground">
                      {t('Total to move')}
                    </p>
                    {data.totalAmount ? (
                      <Amount
                        value={data.totalAmount}
                        size="lg"
                        context="column"
                      />
                    ) : (
                      <p className="text-subtle-foreground">—</p>
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      {t('Expected saving')}
                    </p>
                    {data.expectedSaving ? (
                      <Amount
                        value={data.expectedSaving}
                        size="lg"
                        context="column"
                      />
                    ) : (
                      <p className="text-subtle-foreground">—</p>
                    )}
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">
                      {t('Progress')}
                    </p>
                    <p className="num text-xl font-medium">
                      {done}/{data.stepCount}{' '}
                      <span className="font-sans text-base font-normal text-muted-foreground">
                        {t('steps with matching event fields')}
                      </span>
                    </p>
                  </div>
                </CardContent>
              </Card>

              {data.status === 'PartiallyCompleted' && (
                <Alert tone="warning" title={t('Partially completed')}>
                  {t(
                    '{{done}} of {{total}} steps have matching module event fields. The remaining steps were not completed; see each step for its state.',
                    { done: done ?? 0, total: data.steps.length },
                  )}
                </Alert>
              )}

              {data.steps.length < data.stepCount && (
                <Alert tone="warning" title={t('Execution details incomplete')}>
                  {t(
                    'Live execution records are available for {{recorded}} of {{total}} signed steps. Steps without operation records cannot be shown yet.',
                    { recorded: data.steps.length, total: data.stepCount },
                  )}
                </Alert>
              )}

              <Card>
                <CardHeader
                  title={t('Steps')}
                  description={t(
                    'Payment events are checked against the request, payer, recipient, and amount. Refill events are checked against the request, destination, and amount; other signed fields may be absent from module events.',
                  )}
                />
                <CardContent>
                  <StepTimeline plan={data} />
                </CardContent>
              </Card>
            </div>

            <aside
              aria-label={t('Why this plan')}
              className="grid gap-4 lg:col-span-2"
            >
              <h2 className="text-lg font-semibold">{t('Why this plan')}</h2>
              {data.validations.length > 0 ? (
                <PolicyDecision validations={data.validations} />
              ) : (
                <Alert
                  tone="neutral"
                  title={t('Validation details unavailable')}
                >
                  {t(
                    'The execution record does not include the validator checks for this plan.',
                  )}
                </Alert>
              )}
              {data.aiExplanation ? (
                <AiExplanation
                  model={data.aiExplanation.model}
                  generatedAt={data.aiExplanation.generatedAt}
                >
                  {data.aiExplanation.text}
                </AiExplanation>
              ) : (
                <Alert
                  tone="neutral"
                  title={
                    data.plannerSource === 'RULE_BASED'
                      ? t('No AI explanation')
                      : t('Planner explanation unavailable')
                  }
                >
                  {data.plannerSource === 'RULE_BASED'
                    ? t(
                        'This plan was produced by the rule-based scheduler (earliest deadline first), so there is no AI text. The policy decision above is complete on its own.',
                      )
                    : t(
                        'Planner source and explanation were not persisted with this execution record.',
                      )}
                </Alert>
              )}
              {data.bindingConstraints.length > 0 && (
                <Card>
                  <CardHeader
                    title={t('Binding constraints')}
                    description={t('The limits that shaped this plan.')}
                  />
                  <CardContent>
                    <KeyValueList
                      items={data.bindingConstraints.map((constraint) => ({
                        label: constraint.label,
                        hint: constraint.detail,
                        value: (
                          <span className="num font-medium">
                            {constraint.value}
                          </span>
                        ),
                      }))}
                    />
                  </CardContent>
                </Card>
              )}
              {data.attestation && (
                <Card>
                  <CardHeader
                    title={t('Policy attestation')}
                    description={t(
                      'The signer only sends a plan that carries this signature.',
                    )}
                  />
                  <CardContent>
                    <KeyValueList
                      items={[
                        {
                          label: t('Plan hash'),
                          value: (
                            <span className="num text-sm">
                              {shortHash(data.attestation.planHash)}
                            </span>
                          ),
                        },
                        {
                          label: t('Policy key'),
                          value: <Address address={data.attestation.signer} />,
                        },
                        {
                          label: t('Signed'),
                          value: formatDateTime(data.attestation.signedAt),
                        },
                      ]}
                    />
                  </CardContent>
                </Card>
              )}
            </aside>
          </div>
        )}
      </QueryBoundary>
    </Page>
  );
}
