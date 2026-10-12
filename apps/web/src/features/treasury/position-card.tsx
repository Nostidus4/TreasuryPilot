import { ArrowRight } from 'lucide-react';
import { Link } from 'react-router-dom';

import { Amount } from '@/components/domain/amount';
import { TxHash } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import type { Position } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatBps, ratioPercent, sum, toBigInt } from '@/lib/money';

/**
 * Treasury position (WEB-026, ADR-019): where the money is, how much must
 * stay in the Safe, and why the agent did or did not supply the rest.
 * Every number is the engine's output for the snapshot; nothing is recomputed
 * here except the "free in Safe" remainder for the bar.
 */
export function PositionCard({
  borrowHref,
  position,
}: {
  borrowHref?: string;
  position: Position;
}) {
  const reserve = position.requiredReserve;
  const safe = toBigInt(position.safeUsdc);
  const reserved =
    toBigInt(reserve.total) > safe ? safe : toBigInt(reserve.total);
  const free = safe - reserved;
  const total = sum([position.safeUsdc, position.aUsdc]);

  const segments = [
    {
      key: 'reserve',
      label: t('Required reserve, kept in the Safe'),
      value: reserved,
      className: 'bg-chart-1',
    },
    {
      key: 'free',
      label: t('In the Safe above the reserve'),
      value: free,
      className: 'bg-chart-2',
    },
    {
      key: 'aave',
      label: t('Supplied to Aave V3 (aUSDC)'),
      value: toBigInt(position.aUsdc),
      className: 'bg-chart-3',
    },
  ];
  const { lastAction } = position;

  return (
    <Card>
      <CardHeader
        title={t('Position')}
        description={t('Where the money is, and what must stay liquid.')}
      />
      <CardContent className="grid gap-5">
        <div>
          <p className="text-sm text-muted-foreground">
            {t('Accessible liquidity')}
          </p>
          <Amount value={total} size="xl" />
        </div>

        <div>
          <div
            className="flex h-3 gap-0.5 overflow-hidden rounded-full"
            role="img"
            aria-label={t(
              'Split of accessible liquidity between the required reserve, free Safe balance and Aave',
            )}
          >
            {segments
              .filter((segment) => segment.value > 0n)
              .map((segment) => (
                <span
                  key={segment.key}
                  className={segment.className}
                  style={{ width: `${ratioPercent(segment.value, total)}%` }}
                />
              ))}
          </div>
          <ul className="mt-3 grid gap-1.5">
            {segments.map((segment) => (
              <li
                key={segment.key}
                className="flex items-center justify-between gap-3 text-base"
              >
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden="true"
                    className={`size-2.5 shrink-0 rounded-sm ${segment.className}`}
                  />
                  <span className="truncate">{segment.label}</span>
                </span>
                <Amount value={segment.value} context="column" />
              </li>
            ))}
          </ul>
        </div>

        <div className="grid gap-5 border-t pt-4 md:grid-cols-2">
          <div>
            <h3 className="text-sm font-medium">
              {t('Required Safe reserve')}
            </h3>
            <KeyValueList
              className="mt-2"
              items={[
                {
                  label: t('Payment reserve'),
                  hint: t('Approved and scheduled payments'),
                  value: (
                    <Amount value={reserve.paymentReserve} context="column" />
                  ),
                },
                {
                  label: t('Floor'),
                  hint: t('Always kept, whatever is due'),
                  value: <Amount value={reserve.floor} context="column" />,
                },
                {
                  label: t('Holds'),
                  hint: t('Fees and exceptions in progress'),
                  value: <Amount value={reserve.holds} context="column" />,
                },
                {
                  label: (
                    <span className="font-medium text-foreground">
                      {t('Total')}
                    </span>
                  ),
                  value: <Amount value={reserve.total} context="column" />,
                },
              ]}
            />
          </div>
          <div>
            <h3 className="text-sm font-medium">{t('Idle cash on Aave')}</h3>
            <KeyValueList
              className="mt-2"
              items={[
                {
                  label: t('Available for supply'),
                  hint: t('Safe balance minus the required reserve'),
                  value: (
                    <Amount
                      value={position.availableForSupply}
                      context="column"
                    />
                  ),
                },
                {
                  label: t('Supply APY'),
                  value: (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="num font-medium">
                        {formatBps(position.supplyApyBps)}
                      </span>
                      <Badge tone="warning">{t('Testnet rate')}</Badge>
                    </span>
                  ),
                },
                {
                  label: t('Pool liquidity'),
                  hint: t('What the pool can return right now'),
                  value: (
                    <Amount value={position.poolLiquidity} context="column" />
                  ),
                },
              ]}
            />
          </div>
        </div>

        <div className="rounded-lg border bg-surface-muted p-3">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-medium">
              {t('Last liquidity action')}
            </h3>
            {lastAction.kind === 'NONE' ? (
              <Badge>{t('None yet')}</Badge>
            ) : (
              <>
                <Badge tone="info">
                  {lastAction.kind === 'SUPPLY' ? t('Supply') : t('Withdraw')}
                </Badge>
                <Amount value={lastAction.amount} size="sm" context="column" />
                <span className="text-xs text-muted-foreground">
                  {formatRelative(lastAction.at)}
                </span>
                {lastAction.txHash && <TxHash hash={lastAction.txHash} />}
              </>
            )}
          </div>
          <p className="mt-1.5 text-sm text-muted-foreground">
            <span className="font-medium text-foreground">{t('Why')}:</span>{' '}
            {lastAction.explanation}
          </p>
        </div>

        {borrowHref && (
          <Link
            to={borrowHref}
            className="inline-flex items-center gap-1.5 text-sm font-medium text-primary hover:underline"
          >
            {t('Compare withdraw vs borrow for the next shortfall')}
            <ArrowRight className="size-3.5" aria-hidden="true" />
          </Link>
        )}
      </CardContent>
    </Card>
  );
}
