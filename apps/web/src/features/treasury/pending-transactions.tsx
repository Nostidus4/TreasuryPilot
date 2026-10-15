import { Link } from 'react-router-dom';

import { Amount } from '@/components/domain/amount';
import { TxHash } from '@/components/domain/chain';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState } from '@/components/feedback';
import { Card, CardHeader } from '@/components/ui/card';
import { Alert } from '@/components/ui/misc';
import { usePlanDetails, usePlans } from '@/features/operations/api';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { stepStatus } from '@/lib/status';

const MAX_PLANS = 10;

/** Transactions sent to the network that have no confirmed outcome yet (WEB-019). */
export function PendingTransactions() {
  const scope = useTreasuryScope();
  const plans = usePlans(scope.orgId, scope.treasuryId ?? '');
  const executing = (plans.data?.items ?? []).filter(
    (plan) => plan.status === 'Executing',
  );
  // shortcut: N+1 plan fetches, upgrade when the API lists pending steps
  const shown = executing.slice(0, MAX_PLANS);
  const details = usePlanDetails(
    scope.orgId,
    shown.map((plan) => plan.id),
  );
  const rows = shown.flatMap((plan, index) =>
    (details[index]?.data?.steps ?? [])
      .filter(
        (step) => step.status === 'Submitted' || step.status === 'Pending',
      )
      .map((step) => ({ planId: plan.id, step })),
  );
  const loading = plans.isPending || details.some((query) => query.isPending);
  const failed = plans.isError || details.some((query) => query.isError);
  return (
    <Card>
      <CardHeader title={t('Pending transactions')} />
      {failed ? (
        <Alert tone="danger" className="m-4">
          {t('Pending transactions could not be loaded.')}
        </Alert>
      ) : loading ? (
        <p role="status" className="p-4 text-sm text-muted-foreground">
          {t('Loading')}
        </p>
      ) : rows.length === 0 ? (
        <EmptyState
          title={t('Nothing pending')}
          description={t(
            'Transactions waiting for the network will be listed here.',
          )}
        />
      ) : (
        <ul className="divide-y">
          {rows.map(({ planId, step }) => (
            <li key={step.id} className="flex items-start gap-3 px-4 py-3">
              <span className="min-w-0 flex-1">
                <Link
                  to={`${scope.tBase}/plans/${planId}`}
                  className="block text-base hover:underline"
                >
                  {step.title}
                </Link>
                <span className="text-xs text-subtle-foreground">
                  {planId} · {formatRelative(step.updatedAt)}
                  {step.txHash && (
                    <>
                      {' · '}
                      <TxHash hash={step.txHash} />
                    </>
                  )}
                </span>
              </span>
              {step.amount && <Amount value={step.amount} context="column" />}
              <StatusBadge meta={stepStatus(step.status, step.confirmations)} />
            </li>
          ))}
        </ul>
      )}
      {executing.length > MAX_PLANS && (
        <div className="border-t px-4 py-3 text-sm">
          <Link to={`${scope.tBase}/plans`} className="hover:underline">
            {t('{{count}} more executing plans — see all plans', {
              count: executing.length - MAX_PLANS,
            })}
          </Link>
        </div>
      )}
    </Card>
  );
}
