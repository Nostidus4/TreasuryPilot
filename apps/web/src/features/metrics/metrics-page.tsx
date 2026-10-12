import { format } from 'date-fns';
import { Link } from 'react-router-dom';

import { BarSeriesChart } from '@/components/charts';
import { Amount, AmountHeader } from '@/components/domain/amount';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/misc';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import {
  useOperationsMetrics,
  useSavingsMetrics,
} from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useAssetInfo } from '@/lib/api/chains';
import { t } from '@/lib/i18n';
import { formatUnits } from '@/lib/money';

function Stat({
  hint,
  label,
  value,
}: {
  hint: string;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-lg border bg-surface p-4">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className="num mt-1 text-2xl font-semibold">{value}</p>
      <p className="mt-1 text-xs text-muted-foreground">{hint}</p>
    </div>
  );
}

const percent = (ratio: number) => `${(ratio * 100).toFixed(1)}%`;

/** Operations metrics and savings against baseline B1 (WEB-018). */
export function MetricsPage() {
  const scope = useOrgScope();
  const operations = useOperationsMetrics(scope.orgId);
  const savings = useSavingsMetrics(scope.orgId);
  const info = useAssetInfo();

  return (
    <Page
      title={t('Metrics')}
      description={t(
        'How the treasury operated over the last 14 days, and what the plans saved against paying every invoice on its due date.',
      )}
    >
      <div className="grid gap-6">
        <QueryBoundary
          query={operations}
          loading={<Skeleton className="h-80" />}
        >
          {({ metrics }) => (
            <section aria-label={t('Operations')} className="grid gap-4">
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                <Stat
                  label={t('Payments executed')}
                  value={String(metrics.paymentsCount)}
                  hint={t('Verified on-chain')}
                />
                <Stat
                  label={t('Paid on time')}
                  value={percent(metrics.onTimeRate)}
                  hint={t('On or before the due date')}
                />
                <Stat
                  label={t('Median time to approve')}
                  value={t('{{minutes}} min', {
                    minutes: metrics.medianApprovalMinutes,
                  })}
                  hint={t('From submission to signature')}
                />
                <Stat
                  label={t('Plans from the AI planner')}
                  value={percent(metrics.aiPlanRate)}
                  hint={t('The rest used the rule-based fallback')}
                />
              </div>
              <Card>
                <CardHeader
                  title={t('Payments per day')}
                  description={t(
                    '{{exceptions}} exceptions and {{unknown}} unknown outcomes in the period.',
                    {
                      exceptions: metrics.exceptions,
                      unknown: metrics.unknownOperations,
                    },
                  )}
                />
                <CardContent>
                  <BarSeriesChart
                    summary={t(
                      'Bar chart of the number of payments executed on each of the last 14 days.',
                    )}
                    seriesLabel={t('Payments')}
                    xLabel={t('Day')}
                    data={metrics.series.map((point) => ({
                      label: format(new Date(point.date), 'MMM d'),
                      value: point.paid,
                      display: String(point.paid),
                      note: info
                        ? t('Volume {{amount}} {{symbol}}', {
                            amount: formatUnits(
                              point.volume,
                              info.asset.decimals,
                            ),
                            symbol: info.asset.symbol,
                          })
                        : undefined,
                    }))}
                  />
                </CardContent>
              </Card>
            </section>
          )}
        </QueryBoundary>

        <QueryBoundary query={savings} loading={<Skeleton className="h-64" />}>
          {({ methodology, perRequest, totals }) => (
            <Card className="overflow-hidden">
              <CardHeader
                title={t('Savings against baseline B1')}
                description={t(
                  'B1 pays every invoice in full on its due date.',
                )}
              />
              {perRequest.length === 0 ? (
                <EmptyState
                  title={t('No executed plans yet')}
                  description={t(
                    'Savings appear after the first plan with an early-payment discount is executed.',
                  )}
                />
              ) : (
                <>
                  <CardContent className="grid gap-4 border-b sm:grid-cols-3">
                    <div>
                      <p className="text-sm text-muted-foreground">
                        {t('Baseline B1 would have paid')}
                      </p>
                      <Amount
                        value={totals.baseline}
                        size="lg"
                        context="column"
                      />
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">
                        {t('Actually paid')}
                      </p>
                      <Amount
                        value={totals.actual}
                        size="lg"
                        context="column"
                      />
                    </div>
                    <div>
                      <p className="text-sm text-muted-foreground">
                        {t('Saved')}
                      </p>
                      <Amount value={totals.saved} size="lg" />
                    </div>
                  </CardContent>
                  <Table>
                    <TableHeader>
                      <tr>
                        <TableHead>{t('Invoice')}</TableHead>
                        <TableHead align="right">
                          <AmountHeader label="Baseline" />
                        </TableHead>
                        <TableHead align="right">{t('Actual')}</TableHead>
                        <TableHead align="right">{t('Saved')}</TableHead>
                      </tr>
                    </TableHeader>
                    <TableBody>
                      {perRequest.map((row) => (
                        <TableRow key={row.requestId}>
                          <TableCell>
                            <Link
                              to={`${scope.base}/requests/${row.requestId}`}
                              className="num font-medium hover:underline"
                            >
                              {row.invoiceNumber}
                            </Link>
                            <p className="text-xs text-muted-foreground">
                              {row.vendorName}
                            </p>
                          </TableCell>
                          <TableCell align="right">
                            <Amount
                              value={row.baseline}
                              context="column"
                              muted
                            />
                          </TableCell>
                          <TableCell align="right">
                            <Amount value={row.actual} context="column" />
                          </TableCell>
                          <TableCell align="right">
                            {row.saved === '0' ? (
                              <span className="text-subtle-foreground">—</span>
                            ) : (
                              <Amount value={row.saved} context="column" />
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </>
              )}
              <CardContent className="border-t text-sm text-muted-foreground">
                <span className="font-medium text-foreground">
                  {t('Method')}:
                </span>{' '}
                {methodology}
              </CardContent>
            </Card>
          )}
        </QueryBoundary>
      </div>
    </Page>
  );
}
