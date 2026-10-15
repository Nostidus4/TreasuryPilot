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

import { Amount } from '@/components/domain/amount';
import { Address } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Switch } from '@/components/ui/controls';
import { Skeleton } from '@/components/ui/misc';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { useRequests } from '@/features/requests/api';
import { useForecast, useTreasury } from '@/features/treasury/api';
import {
  BudgetBullets,
  buildBranches,
  LiquidityIcicle,
  OverviewFocusProvider,
  RunwayChart,
  SafeBullets,
} from '@/features/treasury/overview-charts';
import { PendingTransactions } from '@/features/treasury/pending-transactions';
import { PauseDialog } from '@/features/treasury/status-banner';
import { WalletRunways } from '@/features/treasury/wallet-runways';
import { useAssetInfo } from '@/lib/api/chains';
import type { TreasuryState } from '@/lib/api/types';
import { formatDate, formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatBps, sum } from '@/lib/money';
import { mandateStatus, treasuryStatus } from '@/lib/status';
import { cn } from '@/lib/utils';

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-3" aria-busy="true">
      <Skeleton className="h-96 lg:col-span-2" />
      <Skeleton className="h-96" />
      <Skeleton className="h-40 lg:col-span-3" />
    </div>
  );
}

function QueueTiles({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  const rows = [
    {
      label: t('To approve'),
      count: state.queues.approvals,
      to: `${scope.base}/approvals`,
    },
    {
      label: t('To sign on-chain'),
      count: state.queues.governance,
      to: `${scope.base}/governance`,
    },
    {
      label: t('To review'),
      count: state.queues.review,
      to: `${scope.base}/review`,
    },
    {
      label: t('To reconcile'),
      count: state.queues.reconciliation,
      to: `${scope.base}/reconciliation`,
    },
  ];
  return (
    <ul
      className="grid grid-cols-2 gap-3 sm:grid-cols-4"
      aria-label={t('Waiting on people')}
    >
      {rows.map((row) => (
        <li key={row.label}>
          <Link
            to={row.to}
            className="group flex items-center justify-between gap-3 rounded-lg border bg-surface px-4 py-3 hover:border-border-strong"
          >
            <span>
              <span
                className={cn(
                  'num block text-2xl font-semibold leading-none',
                  row.count === 0 && 'text-subtle-foreground',
                )}
              >
                {row.count}
              </span>
              <span className="mt-1 block text-sm text-muted-foreground">
                {row.label}
              </span>
            </span>
            <ArrowRight
              className="size-4 text-subtle-foreground group-hover:text-foreground"
              aria-hidden="true"
            />
          </Link>
        </li>
      ))}
    </ul>
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

function LiquidityHeader({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  const { position } = state;
  const accessible = sum([position.safeUsdc, position.aUsdc]);
  const last = position.lastAction;
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-3">
      <div>
        <p className="text-sm text-muted-foreground">
          {t('Accessible liquidity')}
        </p>
        <Amount value={accessible} size="xl" />
      </div>
      <dl className="flex flex-wrap gap-x-8 gap-y-2 text-sm">
        <div>
          <dt className="text-muted-foreground">{t('Supply APY')}</dt>
          <dd className="flex items-center gap-1.5">
            <span className="num font-medium">
              {formatBps(position.supplyApyBps)}
            </span>
            <Badge tone="warning">{t('Testnet rate')}</Badge>
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t('Pool liquidity')}</dt>
          <dd>
            <Amount value={position.poolLiquidity} size="sm" context="column" />
          </dd>
        </div>
        {last.kind !== 'NONE' && (
          <div title={last.explanation}>
            <dt className="text-muted-foreground">{t('Last action')}</dt>
            <dd className="flex items-center gap-1.5">
              <Badge tone="info">
                {last.kind === 'SUPPLY' ? t('Supply') : t('Withdraw')}
              </Badge>
              <Amount value={last.amount} size="sm" context="column" />
              <span className="text-xs text-subtle-foreground">
                {formatRelative(last.at)}
              </span>
            </dd>
          </div>
        )}
      </dl>
      {state.borrowProposalId && (
        <Link
          to={`${scope.tBase}/borrow/${state.borrowProposalId}`}
          className="inline-flex items-center gap-1 self-end text-sm text-primary hover:underline"
        >
          {t('Withdraw vs borrow')}
          <ArrowRight className="size-3.5" aria-hidden="true" />
        </Link>
      )}
    </div>
  );
}

/** The engine's numbers as-is: reserve parts add up to the total, and the API supplies AvailableForSupply. */
function PositionBreakdown({
  position,
}: {
  position: TreasuryState['position'];
}) {
  const { requiredReserve: reserve } = position;
  const row = (label: string, value: string, strong?: boolean) => (
    <div className="flex items-baseline justify-between gap-4 py-1.5">
      <dt className={strong ? 'font-medium' : 'text-muted-foreground'}>
        {label}
      </dt>
      <dd>
        <Amount value={value} size="sm" context="column" />
      </dd>
    </div>
  );
  return (
    <div
      role="group"
      aria-label={t('Position breakdown')}
      className="grid gap-x-10 text-sm md:grid-cols-2"
    >
      <dl className="divide-y">
        {row(t('Safe USDC'), position.safeUsdc)}
        {row(t('aUSDC (Aave)'), position.aUsdc)}
        {row(t('Available for supply'), position.availableForSupply, true)}
      </dl>
      <dl className="divide-y">
        {row(t('Payment reserve'), reserve.paymentReserve)}
        {row(t('Floor'), reserve.floor)}
        {row(t('Holds'), reserve.holds)}
        {row(t('Required safe reserve'), reserve.total, true)}
      </dl>
    </div>
  );
}

/** Charts first: where the money is, how long it lasts, and what is left today. */
function Overview({ state }: { state: TreasuryState }) {
  const scope = useTreasuryScope();
  const [includeDrafts, setIncludeDrafts] = useState(false);
  const forecast = useForecast(scope.orgId, scope.treasuryId, includeDrafts);
  const requests = useRequests(scope.orgId);
  const info = useAssetInfo(state.treasury.asset);
  if (!info) return <DashboardSkeleton />;
  const units = { decimals: info.asset.decimals, symbol: info.asset.symbol };
  const o1 = state.wallets.find((wallet) => wallet.role === 'O1');
  const branches = buildBranches(state.position, state.wallets);

  return (
    <div className="grid gap-4">
      <QueueTiles state={state} />

      <Card>
        <CardHeader title={t('Liquidity')} />
        <CardContent className="grid gap-5">
          <LiquidityHeader state={state} />
          <PositionBreakdown position={state.position} />
          {state.position.lastAction.kind !== 'NONE' && (
            <p className="text-sm text-muted-foreground">
              <span className="font-medium text-foreground">{t('Why')}:</span>{' '}
              {state.position.lastAction.explanation}
            </p>
          )}
          <LiquidityIcicle branches={branches} units={units} />
        </CardContent>
      </Card>

      {forecast.data && (
        <WalletRunways
          asset={state.treasury.asset}
          forecast={forecast.data}
          units={units}
          wallets={state.wallets}
        />
      )}

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader
            title={t('7-day runway')}
            description={
              o1
                ? t('{{wallet}}, if nothing is refilled', { wallet: o1.label })
                : undefined
            }
            action={
              <label className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                <span>{t('Include drafts')}</span>
                <Switch
                  aria-label={t('Include drafts')}
                  checked={includeDrafts}
                  onCheckedChange={setIncludeDrafts}
                />
              </label>
            }
          />
          <CardContent>
            {forecast.data && requests.data ? (
              <RunwayChart
                forecast={forecast.data}
                requests={requests.data.items.filter(
                  (request) => request.treasuryId === state.treasury.id,
                )}
                requestHref={(id) => `${scope.base}/requests/${id}`}
                includeDrafts={includeDrafts}
                units={units}
                walletLabel={o1?.label ?? t('Payments Safe')}
              />
            ) : forecast.isError || requests.isError ? (
              <ErrorState
                error={forecast.error ?? requests.error}
                onRetry={() => {
                  void forecast.refetch();
                  void requests.refetch();
                }}
              />
            ) : (
              <Skeleton className="h-72" />
            )}
          </CardContent>
        </Card>
        <div className="grid gap-4">
          <Card>
            <CardHeader title={t('Safes')} />
            <CardContent>
              <SafeBullets wallets={state.wallets} units={units} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader
              title={t('Today’s budget')}
              description={t('Resets 00:00 UTC')}
            />
            <CardContent>
              {state.budgets.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t('Limits appear once a mandate is active.')}
                </p>
              ) : (
                <BudgetBullets
                  budgets={state.budgets}
                  dueToday={forecast.data?.days[0]?.outflow ?? '0'}
                  units={units}
                />
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <PendingTransactions />

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Controls state={state} />
        <Activity state={state} />
      </div>
    </div>
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
        t('{{chain}} · block {{block}} · {{when}}', {
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
            <OverviewFocusProvider>
              <Overview state={data} />
            </OverviewFocusProvider>
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
