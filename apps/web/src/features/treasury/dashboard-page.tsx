import { format } from 'date-fns';
import {
  ArrowRight,
  Bot,
  CirclePause,
  Link2,
  Upload,
  User,
} from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { LineSeriesChart } from '@/components/charts';
import { Amount } from '@/components/domain/amount';
import { Address } from '@/components/domain/chain';
import {
  BalanceMeter,
  KeyValueList,
  UsageBar,
} from '@/components/domain/display';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert, Skeleton } from '@/components/ui/misc';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { useForecast, useTreasury } from '@/features/treasury/api';
import { PositionCard } from '@/features/treasury/position-card';
import { PauseDialog } from '@/features/treasury/status-banner';
import { useAssetInfo } from '@/lib/api/chains';
import type { TreasuryState } from '@/lib/api/types';
import { formatDate, formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatUnits } from '@/lib/money';
import { mandateStatus, treasuryStatus } from '@/lib/status';

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-3" aria-busy="true">
      <Skeleton className="h-96 lg:col-span-2" />
      <Skeleton className="h-96" />
      <Skeleton className="h-40 lg:col-span-3" />
    </div>
  );
}

function Queues({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  const rows = [
    {
      label: t('Approvals to sign'),
      count: state.queues.approvals,
      to: `${scope.base}/approvals`,
    },
    {
      label: t('Governance transactions'),
      count: state.queues.governance,
      to: `${scope.base}/governance`,
    },
    {
      label: t('Review items'),
      count: state.queues.review,
      to: `${scope.base}/review`,
    },
    {
      label: t('Payments to reconcile'),
      count: state.queues.reconciliation,
      to: `${scope.base}/reconciliation`,
    },
  ];
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  return (
    <Card>
      <CardHeader
        title={t('Waiting on people')}
        description={
          total === 0
            ? t('Nothing is waiting.')
            : t('{{count}} items need a decision.', { count: total })
        }
      />
      <ul className="divide-y">
        {rows.map((row) => (
          <li key={row.label}>
            <Link
              to={row.to}
              className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-muted"
            >
              <span className="flex-1 text-base">{row.label}</span>
              <span
                className={`num text-lg font-semibold ${row.count === 0 ? 'text-subtle-foreground' : ''}`}
              >
                {row.count}
              </span>
              <ArrowRight
                className="size-4 text-subtle-foreground"
                aria-hidden="true"
              />
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Controls({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  const coverageTone = {
    COMPLETE: 'success',
    PARTIAL: 'warning',
    UNKNOWN: 'neutral',
  } as const;
  const coverageLabel = {
    COMPLETE: t('Complete'),
    PARTIAL: state.coverage.acknowledged
      ? t('Partial — acknowledged')
      : t('Partial'),
    UNKNOWN: t('Not checked'),
  };
  return (
    <Card>
      <CardHeader title={t('Controls')} />
      <CardContent>
        <KeyValueList
          items={[
            {
              label: t('Treasury'),
              value: (
                <StatusBadge meta={treasuryStatus(state.treasury.status)} />
              ),
            },
            {
              label: t('Mandate'),
              hint: state.mandate
                ? t('Expires {{date}}', {
                    date: formatDate(state.mandate.expiresAt),
                  })
                : undefined,
              value: state.mandate ? (
                <Link
                  to={`${scope.tBase}/mandate`}
                  className="inline-flex items-center gap-2 hover:underline"
                >
                  <span className="num">v{state.mandate.version}</span>
                  <StatusBadge meta={mandateStatus(state.mandate.status)} />
                </Link>
              ) : (
                <Link
                  to={`${scope.tBase}/mandate`}
                  className="text-primary underline"
                >
                  {t('Not set — create one')}
                </Link>
              ),
            },
            {
              label: t('Module coverage'),
              hint: state.coverage.details[0],
              value: (
                <Badge tone={coverageTone[state.coverage.status]}>
                  {coverageLabel[state.coverage.status]}
                </Badge>
              ),
            },
            {
              label: t('Module'),
              value: <Address address={state.treasury.moduleAddress} />,
            },
          ]}
        />
      </CardContent>
    </Card>
  );
}

function Runway() {
  const scope = useTreasuryScope();
  const forecast = useForecast(scope.orgId, scope.treasuryId);
  const info = useAssetInfo();
  return (
    <Card>
      <CardHeader
        title={t('7-day runway')}
        description={t(
          'Projected Payments Safe balance if every open request is paid on its due date and nothing is refilled.',
        )}
      />
      <CardContent>
        <QueryBoundary query={forecast} loading={<Skeleton className="h-56" />}>
          {({ alerts, days }) => {
            if (!info) return <Skeleton className="h-56" />;
            const { decimals, symbol } = info.asset;
            const number = (value: string) =>
              Number(formatUnits(value, decimals, { group: false }));
            return (
              <div className="grid gap-3">
                {alerts.map((alert) => (
                  <Alert key={alert.date} tone="warning">
                    {format(new Date(alert.date), 'MMM d')}: {alert.message}
                  </Alert>
                ))}
                <LineSeriesChart
                  summary={t(
                    'Line chart of the projected Payments Safe balance for the next 7 days against its minimum buffer.',
                  )}
                  seriesLabel={t('Projected balance')}
                  xLabel={t('Day')}
                  references={
                    days[0]
                      ? [
                          {
                            value: number(days[0].buffer),
                            label: t('Minimum buffer'),
                          },
                        ]
                      : undefined
                  }
                  data={days.map((day) => ({
                    label: format(new Date(day.date), 'MMM d'),
                    value: number(day.balance),
                    display: `${formatUnits(day.balance, decimals)} ${symbol}`,
                    note:
                      day.outflow !== '0'
                        ? t('Due that day: {{amount}} {{symbol}}', {
                            amount: formatUnits(day.outflow, decimals),
                            symbol,
                          })
                        : undefined,
                  }))}
                />
              </div>
            );
          }}
        </QueryBoundary>
      </CardContent>
    </Card>
  );
}

const actorIcon = { agent: Bot, user: User, chain: Link2 } as const;
const actorLabel = {
  agent: 'Agent',
  user: 'Member',
  chain: 'On-chain',
} as const;

function Activity({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  return (
    <Card>
      <CardHeader title={t('Recent activity')} />
      {state.activity.length === 0 ? (
        <EmptyState
          title={t('No activity yet')}
          description={t(
            'Plans, signatures and on-chain results will be listed here as they happen.',
          )}
        />
      ) : (
        <ol className="divide-y">
          {state.activity.slice(0, 8).map((item) => {
            const Icon = actorIcon[item.actor];
            const body = (
              <>
                <Icon
                  className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-base">{item.text}</span>
                  <span className="text-xs text-subtle-foreground">
                    {t(actorLabel[item.actor])} · {formatRelative(item.at)}
                  </span>
                </span>
              </>
            );
            return (
              <li key={item.id}>
                {item.href ? (
                  <Link
                    to={scope.resolve(item.href)}
                    className="flex gap-3 px-4 py-2.5 hover:bg-surface-muted"
                  >
                    {body}
                  </Link>
                ) : (
                  <div className="flex gap-3 px-4 py-2.5">{body}</div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

/** Treasury dashboard (WEB-010): health at a glance, money first. */
export function DashboardPage() {
  const scope = useTreasuryScope();
  const query = useTreasury(scope.orgId, scope.treasuryId);
  const [pauseOpen, setPauseOpen] = useState(false);
  const state = query.data;

  return (
    <Page
      width="wide"
      title={state?.treasury.name ?? t('Overview')}
      titleSlot={
        state && <StatusBadge meta={treasuryStatus(state.treasury.status)} />
      }
      description={
        state &&
        t('{{chain}} · chain snapshot at block {{block}}, {{when}}', {
          chain: state.treasury.chainName,
          block: state.staleness.blockNumber,
          when: formatRelative(state.staleness.observedAt),
        })
      }
      actions={
        state && (
          <>
            {scope.can('OWN', 'GRD') && state.treasury.status === 'Active' && (
              <Button
                variant="danger-outline"
                onClick={() => setPauseOpen(true)}
              >
                <CirclePause aria-hidden="true" />
                {t('Pause')}
              </Button>
            )}
            <Button asChild variant="primary">
              <Link to={`${scope.base}/requests/upload`}>
                <Upload aria-hidden="true" />
                {t('Upload invoice')}
              </Link>
            </Button>
          </>
        )
      }
    >
      <QueryBoundary query={query} loading={<DashboardSkeleton />}>
        {(data) =>
          data.treasury.status === 'Setup' ? (
            <Card>
              <EmptyState
                title={t('Finish setting up this treasury')}
                description={t(
                  'The module, coverage check and Guardian Safe are not complete yet.',
                )}
                action={
                  <Button asChild variant="primary">
                    <Link
                      to={`${scope.base}/treasuries/new?t=${data.treasury.id}`}
                    >
                      {t('Continue setup')}
                    </Link>
                  </Button>
                }
              />
            </Card>
          ) : (
            <div className="grid gap-4 lg:grid-cols-3">
              <div className="grid content-start gap-4 lg:col-span-2">
                <PositionCard
                  position={data.position}
                  borrowHref={
                    data.borrowProposalId
                      ? `${scope.tBase}/borrow/${data.borrowProposalId}`
                      : undefined
                  }
                />
                <Card>
                  <CardHeader
                    title={t('Safes')}
                    description={t(
                      'Balance against each Safe’s minimum buffer and target.',
                    )}
                  />
                  <ul className="divide-y">
                    {data.wallets
                      .filter((wallet) => wallet.role !== 'GUARDIAN')
                      .map((wallet) => (
                        <li
                          key={wallet.safeAddress}
                          className="grid gap-3 p-4 md:grid-cols-[14rem_1fr] md:items-center"
                        >
                          <div className="min-w-0">
                            <p className="flex items-center gap-2 text-base font-medium">
                              {wallet.label}
                              <Badge tone="outline">{wallet.role}</Badge>
                            </p>
                            <Address address={wallet.safeAddress} />
                          </div>
                          <div>
                            <Amount value={wallet.balance} size="lg" />
                            <div className="mt-2">
                              <BalanceMeter
                                balance={wallet.balance}
                                buffer={wallet.buffer}
                                target={wallet.target}
                              />
                            </div>
                          </div>
                        </li>
                      ))}
                  </ul>
                </Card>
                <Runway />
              </div>

              <div className="grid content-start gap-4">
                <Queues state={data} />
                <Card>
                  <CardHeader
                    title={t('Today’s budget')}
                    description={t('Resets at 00:00 UTC. Enforced on-chain.')}
                  />
                  <CardContent className="grid gap-4">
                    {data.budgets.length === 0 && (
                      <p className="text-sm text-muted-foreground">
                        {t('Limits appear once a mandate is active.')}
                      </p>
                    )}
                    {data.budgets.map((budget) => (
                      <div key={budget.action}>
                        <UsageBar
                          label={
                            budget.action === 'PAY'
                              ? t('Payments')
                              : t('Refills')
                          }
                          used={budget.usedToday}
                          limit={budget.dailyLimit}
                        />
                        <p className="mt-1 text-xs text-muted-foreground">
                          {t('Per request up to')}{' '}
                          <Amount
                            value={budget.perRequest}
                            size="sm"
                            context="column"
                            muted
                          />
                        </p>
                      </div>
                    ))}
                  </CardContent>
                </Card>
                <Controls state={data} />
                <Activity state={data} />
              </div>
            </div>
          )
        }
      </QueryBoundary>
      {state && (
        <PauseDialog
          open={pauseOpen}
          onOpenChange={setPauseOpen}
          treasuryId={state.treasury.id}
        />
      )}
    </Page>
  );
}
