import { format } from 'date-fns';
import { Check } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { LineSeriesChart } from '@/components/charts';
import { Amount } from '@/components/domain/amount';
import { KeyValueList } from '@/components/domain/display';
import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
import { RadioCard, RadioGroup } from '@/components/ui/controls';
import { Alert } from '@/components/ui/misc';
import { useTreasuryScope } from '@/features/orgs/org-scope';
import {
  useAcceptFeePolicy,
  useBorrowProposal,
  useFeePolicy,
  usePlanFeeDecision,
} from '@/features/treasury/api';
import { errorMessage } from '@/lib/api/http';
import type { BorrowProposal, FeePolicy } from '@/lib/api/types';
import { formatDate, formatDateTime, formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatBps, formatUnits } from '@/lib/money';
import { cn } from '@/lib/utils';

const PROPOSAL = 'proposal';
const gwei = (value: number) => `${value} gwei`;
const eth = (wei: string) =>
  `${formatUnits(wei, 18, { minFraction: 4, maxFraction: 6 })} ETH`;

function HeldPlanBanner({
  canDecide,
  held,
  orgId,
  treasuryId,
}: {
  canDecide: boolean;
  held: FeePolicy['heldPlans'][number];
  orgId: string;
  treasuryId: string;
}) {
  const pay = usePlanFeeDecision(orgId, treasuryId, 'accept');
  const defer = usePlanFeeDecision(orgId, treasuryId, 'defer');
  const error = pay.error ?? defer.error;
  return (
    <Alert
      tone="warning"
      title={t('{{title}} is waiting on a network fee', { title: held.title })}
      action={
        canDecide && (
          <div className="flex gap-2">
            <Button
              variant="primary"
              loading={pay.isPending}
              disabled={defer.isPending}
              onClick={() => pay.mutate(held.planId)}
            >
              {t('Pay now at {{fee}}', { fee: eth(held.estimatedFeeWei) })}
            </Button>
            <Button
              loading={defer.isPending}
              disabled={pay.isPending}
              onClick={() => defer.mutate(held.planId)}
            >
              {t('Defer')}
            </Button>
          </div>
        )
      }
    >
      {t('Estimated fee {{fee}}. Decide by {{deadline}}.', {
        fee: eth(held.estimatedFeeWei),
        deadline: formatDateTime(held.deadline),
      })}
      {!canDecide && ` ${t('Only Finance can decide.')}`}
      {error && <span role="alert"> {errorMessage(error)}</span>}
    </Alert>
  );
}

/**
 * Fee policy (WEB-024, M16-D11): the system proposes, the Owner accepts it or
 * picks a preset. There is no free typing of fee values in M1.
 */
export function FeesPage() {
  const scope = useTreasuryScope();
  const query = useFeePolicy(scope.orgId, scope.treasuryId);
  const accept = useAcceptFeePolicy(scope.orgId, scope.treasuryId);
  const [choice, setChoice] = useState(PROPOSAL);
  const canAccept = scope.can('OWN');

  return (
    <Page
      title={t('Fee policy')}
      description={t(
        'The most the agent may pay the network per transaction. If the network asks for more, the plan waits and a review item is raised; a payment is never sent above the cap.',
      )}
    >
      <QueryBoundary query={query}>
        {(policy) => (
          <div className="grid items-start gap-4 lg:grid-cols-5">
            {policy.heldPlans.length > 0 && (
              <div className="grid gap-2 lg:col-span-5">
                {policy.heldPlans.map((held) => (
                  <HeldPlanBanner
                    key={held.planId}
                    held={held}
                    canDecide={scope.can('FIN')}
                    orgId={scope.orgId}
                    treasuryId={scope.treasuryId}
                  />
                ))}
              </div>
            )}
            <div className="grid gap-4 lg:col-span-3">
              <Card>
                <CardHeader
                  title={t('Choose a fee policy')}
                  description={t(
                    'Proposed {{when}} from the last 7 days of network fees.',
                    {
                      when: formatRelative(policy.proposal.proposedAt),
                    },
                  )}
                />
                <CardContent className="grid gap-4">
                  <KeyValueList
                    items={[
                      {
                        label: t('Average fee per plan'),
                        value: eth(policy.basis.avgPlanFeeWei),
                      },
                      {
                        label: t('90th percentile fee per plan'),
                        value: eth(policy.basis.p90PlanFeeWei),
                      },
                      {
                        label: t('Plans per day'),
                        value: policy.basis.plansPerDay,
                      },
                    ]}
                  />
                  <RadioGroup
                    value={choice}
                    onValueChange={setChoice}
                    aria-label={t('Fee policy')}
                    disabled={!canAccept}
                  >
                    <RadioCard value={PROPOSAL}>
                      <span className="flex flex-wrap items-center gap-2">
                        <span className="text-base font-medium">
                          {t('System proposal')}
                        </span>
                        <Badge tone="info">{t('Recommended')}</Badge>
                        <span className="num ml-auto text-base">
                          {t('max {{max}} · priority {{priority}}', {
                            max: gwei(policy.proposal.maxFeeGwei),
                            priority: gwei(policy.proposal.priorityGwei),
                          })}
                        </span>
                      </span>
                      <span className="mt-1 block text-sm text-muted-foreground">
                        {policy.proposal.rationale}
                      </span>
                    </RadioCard>
                    {policy.presets.map((preset) => (
                      <RadioCard key={preset.id} value={preset.id}>
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-medium">
                            {t(preset.label)}
                          </span>
                          <span className="num ml-auto text-base">
                            {t('max {{max}} · priority {{priority}}', {
                              max: gwei(preset.maxFeeGwei),
                              priority: gwei(preset.priorityGwei),
                            })}
                          </span>
                        </span>
                        <span className="mt-1 block text-sm text-muted-foreground">
                          {preset.note}
                        </span>
                      </RadioCard>
                    ))}
                  </RadioGroup>
                </CardContent>
                <CardFooter>
                  {!canAccept && (
                    <p className="mr-auto text-sm text-muted-foreground">
                      {t('Only an Owner can accept a fee policy.')}
                    </p>
                  )}
                  {accept.isError && (
                    <p
                      role="alert"
                      className="mr-auto text-sm text-danger-foreground"
                    >
                      {errorMessage(accept.error)}
                    </p>
                  )}
                  <Button
                    variant="primary"
                    disabled={!canAccept}
                    loading={accept.isPending}
                    onClick={() =>
                      accept.mutate(
                        { preset: choice === PROPOSAL ? undefined : choice },
                        {
                          onSuccess: () =>
                            toast.success(t('Fee policy accepted')),
                        },
                      )
                    }
                  >
                    <Check aria-hidden="true" />
                    {t('Accept')}
                  </Button>
                </CardFooter>
              </Card>

              <Card>
                <CardHeader
                  title={t('Network base fee, last 7 days')}
                  description={t('Observed on the treasury’s chain, in gwei.')}
                />
                <CardContent>
                  <LineSeriesChart
                    summary={t(
                      'Line chart of the network base fee over the last 7 days against the current fee cap.',
                    )}
                    seriesLabel={t('Base fee')}
                    xLabel={t('Time')}
                    yTickFormatter={(value) => String(value)}
                    references={[
                      {
                        value: policy.current.maxFeeGwei,
                        label: t('Current cap'),
                      },
                    ]}
                    data={policy.observations.map((point) => ({
                      label: format(new Date(point.at), 'MMM d HH:mm'),
                      value: point.baseFeeGwei,
                      display: gwei(point.baseFeeGwei),
                    }))}
                  />
                </CardContent>
              </Card>
            </div>

            <Card className="lg:col-span-2">
              <CardHeader title={t('Active policy')} />
              <CardContent className="grid gap-4">
                <KeyValueList
                  items={[
                    {
                      label: t('Max fee per gas'),
                      value: (
                        <span className="num font-medium">
                          {gwei(policy.current.maxFeeGwei)}
                        </span>
                      ),
                    },
                    {
                      label: t('Priority fee'),
                      value: (
                        <span className="num font-medium">
                          {gwei(policy.current.priorityGwei)}
                        </span>
                      ),
                    },
                    { label: t('Source'), value: policy.current.source },
                  ]}
                />
                <h3 className="text-sm font-medium">{t('Accepted fees')}</h3>
                <ul className="grid gap-2 text-sm">
                  {policy.history.map((entry) => (
                    <li key={entry.id}>
                      <span className="font-medium">{entry.label}</span>{' '}
                      <span className="num">{entry.detail}</span>
                      <span className="block text-muted-foreground">
                        {t('{{by}}, {{when}}', {
                          by: entry.by,
                          when: formatRelative(entry.at),
                        })}
                      </span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          </div>
        )}
      </QueryBoundary>
    </Page>
  );
}

function OptionCard({
  recommended,
  rows,
  title,
}: {
  recommended: boolean;
  rows: Array<{ label: string; value: ReactNode; hint?: string }>;
  title: string;
}) {
  return (
    <Card className={cn(recommended && 'border-primary')}>
      <CardHeader
        title={title}
        action={recommended && <Badge tone="success">{t('Lower cost')}</Badge>}
      />
      <CardContent>
        <KeyValueList items={rows} />
      </CardContent>
    </Card>
  );
}

const healthFactor = (value: number) =>
  value === 0 ? t('No debt') : value.toFixed(2);

function Comparison({ proposal }: { proposal: BorrowProposal }) {
  return (
    <div className="grid gap-4">
      <Alert
        tone="neutral"
        title={t('No transaction without owner authorization')}
      >
        {t(
          'This is a comparison, not an action. The agent cannot borrow. A borrow would need a governance transaction signed by the Safe owners.',
        )}
      </Alert>

      <Card>
        <CardHeader title={t('Why this comparison exists')} />
        <CardContent className="grid gap-4">
          <p className="text-base">{proposal.reason}</p>
          <KeyValueList
            items={[
              {
                label: t('Shortfall to cover'),
                value: <Amount value={proposal.shortfall} />,
              },
              { label: t('Needed by'), value: formatDate(proposal.dueAt) },
            ]}
          />
        </CardContent>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <OptionCard
          title={t('Withdraw from Aave')}
          recommended={proposal.recommended === 'WITHDRAW'}
          rows={[
            {
              label: t('Available to withdraw'),
              value: (
                <Amount value={proposal.withdraw.available} context="column" />
              ),
            },
            {
              label: t('Cost over 7 days'),
              hint: proposal.withdraw.note,
              value: <Amount value={proposal.withdraw.cost} context="column" />,
            },
            {
              label: t('Health factor after'),
              value: (
                <span className="num">
                  {healthFactor(proposal.healthFactorBefore)}
                </span>
              ),
            },
          ]}
        />
        <OptionCard
          title={t('Borrow against the position')}
          recommended={proposal.recommended === 'BORROW'}
          rows={[
            {
              label: t('Amount to borrow'),
              value: <Amount value={proposal.borrow.amount} context="column" />,
            },
            {
              label: t('Borrow APR'),
              value: (
                <span className="inline-flex items-center gap-1.5">
                  <span className="num">
                    {formatBps(proposal.borrow.aprBps)}
                  </span>
                  <Badge tone="warning">{t('Testnet rate')}</Badge>
                </span>
              ),
            },
            {
              label: t('Cost over 7 days'),
              hint: proposal.borrow.note,
              value: <Amount value={proposal.borrow.cost7d} context="column" />,
            },
            {
              label: t('Health factor'),
              hint: t('Below 1.00 the position can be liquidated.'),
              value: (
                <span className="num">
                  {healthFactor(proposal.healthFactorBefore)} →{' '}
                  {healthFactor(proposal.healthFactorAfter)}
                </span>
              ),
            },
          ]}
        />
      </div>

      <Alert tone="info" title={t('Engine recommendation')}>
        {proposal.recommended === 'WITHDRAW'
          ? t('Withdraw: it costs less over the period and creates no debt.')
          : t(
              'Borrow: it costs less than giving up the supply interest over the period.',
            )}
      </Alert>
    </div>
  );
}

/** Borrow proposal view (WEB-027, ADR-019 D6): read-only comparison. */
export function BorrowProposalPage() {
  const scope = useTreasuryScope();
  const { id = '' } = useParams();
  const query = useBorrowProposal(scope.orgId, scope.treasuryId, id);
  return (
    <Page
      width="narrow"
      crumbs={[
        { label: t('Overview'), to: scope.tBase },
        { label: t('Borrow proposal') },
      ]}
      title={t('Withdraw or borrow?')}
      description={t(
        'How the two ways of covering a shortfall compare for this snapshot.',
      )}
    >
      <QueryBoundary query={query}>
        {(proposal) => <Comparison proposal={proposal} />}
      </QueryBoundary>
    </Page>
  );
}
