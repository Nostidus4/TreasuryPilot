import { ArrowRight, Plus } from 'lucide-react';
import { Link } from 'react-router-dom';

import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useTreasuries } from '@/features/treasury/api';
import type { TreasurySummary } from '@/lib/api/types';
import { t } from '@/lib/i18n';

const coverageTone = {
  COMPLETE: 'success',
  PARTIAL: 'warning',
  UNKNOWN: 'neutral',
} as const;

function TreasuryRow({ item }: { item: TreasurySummary }) {
  const scope = useOrgScope();
  return (
    <li>
      <Link
        to={`${scope.base}/t/${item.id}`}
        className="grid gap-3 rounded-lg border p-4 hover:border-border-strong sm:grid-cols-[minmax(0,1fr)_auto_auto] sm:items-center"
      >
        <span className="min-w-0">
          <span className="block truncate font-medium">
            {item.chainName} · {item.assetSymbol}
            {item.assetIsTest && (
              <Badge className="ml-2" tone="warning">
                {t('Test')}
              </Badge>
            )}
          </span>
          <span className="mt-1 block text-sm text-muted-foreground">
            {t('Chain {{chainId}} · {{decimals}} decimals', {
              chainId: item.chainId,
              decimals: item.assetDecimals,
            })}
          </span>
        </span>
        <span className="flex flex-wrap gap-2">
          <Badge tone="neutral">{t(item.status)}</Badge>
          <Badge tone={coverageTone[item.coverage]}>
            {t('Coverage: {{status}}', { status: item.coverage })}
          </Badge>
        </span>
        <ArrowRight
          className="hidden size-4 text-subtle-foreground sm:block"
          aria-hidden="true"
        />
      </Link>
    </li>
  );
}

/** Organization view: each treasury keeps its own chain, asset, and controls. */
export function TreasuryPortfolioPage() {
  const scope = useOrgScope();
  const query = useTreasuries(scope.orgId);

  return (
    <Page
      width="wide"
      title={t('Treasuries')}
      description={t(
        'Each treasury is managed independently on its own chain and asset. Balances and limits are shown within that treasury.',
      )}
      actions={
        scope.can('OWN', 'ADM') && (
          <Button asChild variant="primary">
            <Link to={`${scope.base}/treasuries/new`}>
              <Plus aria-hidden="true" />
              {t('Add a treasury')}
            </Link>
          </Button>
        )
      }
    >
      <QueryBoundary query={query}>
        {({ items }) =>
          items.length === 0 ? (
            <Card>
              <CardContent>
                <EmptyState
                  title={t('No treasuries yet')}
                  description={t(
                    'Create a treasury to start managing funds on a supported chain.',
                  )}
                  action={
                    scope.can('OWN', 'ADM') ? (
                      <Button asChild variant="primary">
                        <Link to={`${scope.base}/treasuries/new`}>
                          <Plus aria-hidden="true" />
                          {t('Create treasury')}
                        </Link>
                      </Button>
                    ) : undefined
                  }
                />
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardHeader
                title={t('{{count}} treasuries', { count: items.length })}
                description={t(
                  'Amounts and counters stay with their treasury; no totals are calculated across assets.',
                )}
              />
              <CardContent>
                <ul className="grid gap-3" aria-label={t('Treasuries')}>
                  {items.map((item) => (
                    <TreasuryRow key={item.id} item={item} />
                  ))}
                </ul>
              </CardContent>
            </Card>
          )
        }
      </QueryBoundary>
    </Page>
  );
}
