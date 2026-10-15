import { Check } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { useParams } from 'react-router-dom';
import { toast } from 'sonner';

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
  feeErrorMessage,
  useFeePolicy,
  useHeldFeePlans,
  usePlanFeeDecision,
} from '@/features/treasury/api';
import type {
  BorrowProposal,
  FeePresetId,
  FeeReviewItem,
} from '@/lib/api/types';
import { formatDate, formatDateTime, formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatBps, formatUnits, toBigInt } from '@/lib/money';
import { cn } from '@/lib/utils';

const eth = (wei: string) => {
  const value = toBigInt(wei);
  // Below 6 decimals the amount would render as 0.000000.
  if (value > 0n && value < 10n ** 12n) return '< 0.000001 ETH';
  return `${formatUnits(value, 18, { minFraction: 4, maxFraction: 6 })} ETH`;
};

const PRESETS: Array<{
  id: FeePresetId;
  label: string;
  multiplier: number;
  tip: number;
  note: string;
}> = [
  {
    id: 'ECONOMY',
    label: 'Economy',
    multiplier: 1.5,
    tip: 25,
    note: 'May wait several blocks when the network is busy.',
  },
  {
    id: 'NORMAL',
    label: 'Normal',
    multiplier: 2,
    tip: 50,
    note: 'Recommended for everyday payments.',
  },
  {
    id: 'FAST',
    label: 'Fast',
    multiplier: 3,
    tip: 75,
    note: 'For deadlines within the hour.',
  },
];
const presetLabel = (id: FeePresetId) =>
  PRESETS.find((preset) => preset.id === id)?.label ?? id;
const multiplierLabel = (bps: number) => `${bps / 10_000}× base fee`;

function HeldPlanBanner({
  canDecide,
  held,
  orgId,
}: {
  canDecide: boolean;
  held: FeeReviewItem;
  orgId: string;
}) {
  const pay = usePlanFeeDecision(orgId, 'accept');
  const defer = usePlanFeeDecision(orgId, 'defer');
  const error = pay.error ?? defer.error;
  const planId = held.planId ?? '';
  const fee = eth(held.feeEstimateWei ?? '0');
  return (
    <Alert
      tone="warning"
      title={t('Plan {{id}} is waiting on a network fee', {
        id: planId.slice(0, 8),
      })}
      action={
        canDecide && (
          <div className="flex gap-2">
            <Button
              variant="primary"
              loading={pay.isPending}
              disabled={defer.isPending}
              onClick={() => pay.mutate(planId)}
            >
              {t('Pay now at {{fee}}', { fee })}
            </Button>
            <Button
              loading={defer.isPending}
              disabled={pay.isPending}
              onClick={() => defer.mutate(planId)}
            >
              {t('Defer')}
            </Button>
          </div>
        )
      }
    >
      {t('Estimated fee {{fee}}. Decide by {{deadline}}.', {
        fee,
        deadline: formatDateTime(held.slaDueAt),
      })}
      {!canDecide && ` ${t('Only an Owner, Finance or Operator can decide.')}`}
      {error && <span role="alert"> {feeErrorMessage(error)}</span>}
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
  const held = useHeldFeePlans(scope.orgId, scope.treasuryId);
  const accept = useAcceptFeePolicy(scope.orgId, scope.treasuryId);
  const [choice, setChoice] = useState<FeePresetId | null>(null);
  const canAccept = scope.can('OWN');
  // The backend lets Owner, Finance and Operator decide held plans.
  const canDecide = scope.can('OWN', 'FIN', 'OPR');

  return (
    <Page
      title={t('Fee policy')}
      description={t(
        'The most the agent may pay the network per transaction. If the network asks for more, the plan waits and a review item is raised; a payment is never sent above the cap.',
      )}
    >
      <QueryBoundary query={query}>
        {(policy) => {
          const proposal = policy.proposal;
          const selected = choice ?? proposal?.preset ?? 'NORMAL';
          return (
            <div className="grid items-start gap-4 lg:grid-cols-5">
              {(held.data?.items.length ?? 0) > 0 && (
                <div className="grid gap-2 lg:col-span-5">
                  {held.data?.items.map((item) => (
                    <HeldPlanBanner
                      key={item.id}
                      held={item}
                      canDecide={canDecide}
                      orgId={scope.orgId}
                    />
                  ))}
                </div>
              )}
              <Card className="lg:col-span-3">
                <CardHeader
                  title={t('Choose a fee policy')}
                  description={
                    proposal
                      ? t(
                          'Proposed from the last 7 days of network fees. Presets other than Normal recalculate the limits when accepted.',
                        )
                      : t(
                          'No current proposal. Ask an Owner to open this page to generate one.',
                        )
                  }
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
                    value={selected}
                    onValueChange={(value) => setChoice(value as FeePresetId)}
                    aria-label={t('Fee policy')}
                    disabled={!canAccept}
                  >
                    {PRESETS.map((preset) => (
                      <RadioCard key={preset.id} value={preset.id}>
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="text-base font-medium">
                            {t(preset.label)}
                          </span>
                          {proposal?.preset === preset.id && (
                            <Badge tone="info">{t('Recommended')}</Badge>
                          )}
                          <span className="num ml-auto text-base">
                            {t('max {{max}} · tip at p{{tip}}', {
                              max: multiplierLabel(preset.multiplier * 10_000),
                              tip: preset.tip,
                            })}
                          </span>
                        </span>
                        <span className="mt-1 block text-sm text-muted-foreground">
                          {t(preset.note)}
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
                      {feeErrorMessage(accept.error)}
                    </p>
                  )}
                  <Button
                    variant="primary"
                    disabled={!canAccept || !policy.proposalId}
                    loading={accept.isPending}
                    onClick={() =>
                      policy.proposalId &&
                      accept.mutate(
                        { proposalId: policy.proposalId, preset: selected },
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

              <Card className="lg:col-span-2">
                <CardHeader title={t('Active policy')} />
                <CardContent className="grid gap-4">
                  {policy.active ? (
                    <KeyValueList
                      items={[
                        {
                          label: t('Preset'),
                          value: t(presetLabel(policy.active.preset)),
                        },
                        {
                          label: t('Max fee'),
                          value: multiplierLabel(
                            policy.active.maxFeeMultiplierBps,
                          ),
                        },
                        {
                          label: t('Per-plan threshold'),
                          value: eth(policy.active.perPlanThresholdWei),
                        },
                        {
                          label: t('Daily budget'),
                          value: eth(policy.active.dailyBudgetWei),
                        },
                        {
                          label: t('Spent today'),
                          value: eth(policy.spentTodayWei),
                        },
                        {
                          label: t('Accepted'),
                          value: policy.active.acceptedAt
                            ? formatRelative(policy.active.acceptedAt)
                            : '-',
                        },
                      ]}
                    />
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      {t('No fee policy has been accepted yet.')}
                    </p>
                  )}
                  <h3 className="text-sm font-medium">{t('Accepted fees')}</h3>
                  <ul className="grid gap-2 text-sm">
                    {policy.history.map((entry) => (
                      <li key={entry.id}>
                        {entry.kind === 'POLICY' ? (
                          <>
                            <span className="font-medium">
                              {t('Preset {{preset}}', {
                                preset: presetLabel(entry.preset),
                              })}
                            </span>{' '}
                            <span className="num">
                              {multiplierLabel(entry.maxFeeMultiplierBps)}
                            </span>
                          </>
                        ) : (
                          <>
                            <span className="font-medium">
                              {t('Held plan {{id}}', {
                                id: entry.planId.slice(0, 8),
                              })}
                            </span>{' '}
                            <span className="num">
                              {t('cap {{cap}}', {
                                cap: eth(entry.acceptedCapWei),
                              })}
                            </span>
                          </>
                        )}
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
          );
        }}
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
