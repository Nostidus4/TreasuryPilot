import { format, parseISO } from 'date-fns';
import { Link } from 'react-router-dom';

import { BarSeriesChart, LineSeriesChart } from '@/components/charts';
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

// Date-only strings: parseISO reads them as local days, new Date() as UTC.
const dayLabel = (date: string) => format(parseISO(date), 'MMM d');

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
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
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
                <Stat
                  label={t('Interventions per request')}
                  value={metrics.interventionsPerRequest.toFixed(2)}
                  hint={t('Human review actions on paid requests')}
                />
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                <Card>
                  <CardHeader
                    title={t('Completion and on-time')}
                    description={t('Share of requests in the period.')}
                  />
                  <CardContent>
                    <BarSeriesChart
                      summary={t(
                        'Bar chart of the completion rate and the on-time rate.',
                      )}
                      seriesLabel={t('Rate')}
                      xLabel={t('Measure')}
                      yTickFormatter={(value) => `${value}%`}
                      data={[
                        [t('Completed'), metrics.completionRate],
                        [t('On time'), metrics.onTimeRate],
                      ].map(([label, ratio]) => ({
                        label: String(label),
                        value: Number(ratio) * 100,
                        display: percent(Number(ratio)),
                      }))}
                    />
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader
                    title={t('Fees by step type')}
                    description={t(
                      '{{count}} transactions, total {{total}} ETH.',
                      {
                        count: metrics.txCount,
                        total: formatUnits(metrics.fees.totalWei, 18),
                      },
                    )}
                  />
                  <CardContent>
                    {Object.keys(metrics.fees.byStepType).length === 0 ? (
                      <p className="text-sm text-muted-foreground">
                        {t('No fees were paid in this period.')}
                      </p>
                    ) : (
                      <BarSeriesChart
                        summary={t(
                          'Bar chart of network fees paid, by transaction step type.',
                        )}
                        seriesLabel={t('Fees (ETH)')}
                        xLabel={t('Step type')}
                        yTickFormatter={(value) => String(value)}
                        // Float only sets the bar height; the label text is exact wei.
                        data={Object.entries(metrics.fees.byStepType).map(
                          ([step, wei]) => ({
                            label: step,
                            value: Number(
                              formatUnits(wei, 18, { group: false }),
                            ),
                            display: `${formatUnits(wei, 18)} ETH`,
                          }),
                        )}
                      />
                    )}
                  </CardContent>
                </Card>
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                {[
                  {
                    title: t('Completed per day'),
                    seriesLabel: t('Completed'),
                    pick: (p: (typeof metrics.series)[number]) => p.completed,
                  },
                  {
                    title: t('Paid on time per day'),
                    seriesLabel: t('On time'),
                    pick: (p: (typeof metrics.series)[number]) => p.onTime,
                  },
                  {
                    title: t('Interventions per day'),
                    seriesLabel: t('Interventions'),
                    pick: (p: (typeof metrics.series)[number]) =>
                      p.interventions,
                  },
                ].map(({ pick, seriesLabel, title }) => (
                  <Card key={title}>
                    <CardHeader title={title} />
                    <CardContent>
                      <LineSeriesChart
                        summary={t('Line chart of {{series}} for each day.', {
                          series: title,
                        })}
                        seriesLabel={seriesLabel}
                        xLabel={t('Day')}
                        data={metrics.series.map((point) => ({
                          label: dayLabel(point.date),
                          value: pick(point),
                          display: String(pick(point)),
                        }))}
                      />
                    </CardContent>
                  </Card>
                ))}
                <Card>
                  <CardHeader title={t('Fees per day')} />
                  <CardContent>
                    <LineSeriesChart
                      summary={t(
                        'Line chart of network fees paid for each day.',
                      )}
                      seriesLabel={t('Fees (ETH)')}
                      xLabel={t('Day')}
                      yTickFormatter={(value) => String(value)}
                      // Float only sets the point height; the label text is exact wei.
                      data={metrics.series.map((point) => ({
                        label: dayLabel(point.date),
                        value: Number(
                          formatUnits(point.feesWei, 18, { group: false }),
                        ),
                        display: `${formatUnits(point.feesWei, 18)} ETH`,
                      }))}
                    />
                  </CardContent>
                </Card>
              </div>
              <Card>
                <CardHeader title={t('Payment volume per day')} />
                <CardContent>
                  <LineSeriesChart
                    summary={t(
                      'Line chart of the payment volume executed on each of the last 14 days.',
                    )}
                    seriesLabel={t('Volume')}
                    xLabel={t('Day')}
                    data={metrics.series.map((point) => ({
                      label: dayLabel(point.date),
                      value: Number(
                        formatUnits(point.volume, info?.asset.decimals ?? 6, {
                          group: false,
                        }),
                      ),
                      display:
                        `${formatUnits(point.volume, info?.asset.decimals ?? 6)} ${info?.asset.symbol ?? ''}`.trim(),
                    }))}
                  />
                </CardContent>
              </Card>
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
                      label: dayLabel(point.date),
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
          {({ methodology, perRequest, skipped, totals, warnings }) => (
            <Card className="overflow-hidden">
              <CardHeader
                title={t('Savings against baseline B1')}
                description={t(
                  'Earliest-deadline-first rule baseline under the active mandate caps.',
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
                        <TableHead
                          align="right"
                          className="hidden md:table-cell"
                        >
                          {t('Actual')}
                        </TableHead>
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
                          <TableCell
                            align="right"
                            className="hidden md:table-cell"
                          >
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
                {skipped > 0 && (
                  <p className="mt-2">
                    {t('Not compared')}: {skipped}
                  </p>
                )}
                {warnings.map((warning) => (
                  <p key={warning} className="mt-2">
                    {warning}
                  </p>
                ))}
              </CardContent>
            </Card>
          )}
        </QueryBoundary>
      </div>
    </Page>
  );
}
