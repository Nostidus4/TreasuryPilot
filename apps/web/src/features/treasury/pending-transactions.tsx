import { Link } from 'react-router-dom';

import { Amount } from '@/components/domain/amount';
import { TxHash } from '@/components/domain/chain';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState } from '@/components/feedback';
import { Card, CardHeader } from '@/components/ui/card';
import { usePlan, usePlans } from '@/features/operations/api';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { stepStatus } from '@/lib/status';

function PlanPending({ planId }: { planId: string }) {
  const scope = useTreasuryScope();
  const plan = usePlan(scope.orgId, planId);
  const steps = (plan.data?.steps ?? []).filter(
    (step) => step.status === 'Submitted' || step.status === 'Pending',
  );
  return steps.map((step) => (
    <li key={step.id} className="flex items-start gap-3 px-4 py-3">
      <span className="min-w-0 flex-1">
        <Link
          to={`${scope.base}/plans/${planId}`}
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
  ));
}

/** Transactions sent to the network that have no confirmed outcome yet (WEB-019). */
export function PendingTransactions() {
  const scope = useTreasuryScope();
  const plans = usePlans(scope.orgId, scope.treasuryId ?? '');
  const executing = (plans.data?.items ?? []).filter(
    (plan) => plan.status === 'Executing',
  );
  return (
    <Card>
      <CardHeader title={t('Pending transactions')} />
      {executing.length === 0 ? (
        <EmptyState
          title={t('Nothing pending')}
          description={t(
            'Transactions waiting for the network will be listed here.',
          )}
        />
      ) : (
        <ul className="divide-y">
          {executing.map((plan) => (
            <PlanPending key={plan.id} planId={plan.id} />
          ))}
        </ul>
      )}
    </Card>
  );
}
