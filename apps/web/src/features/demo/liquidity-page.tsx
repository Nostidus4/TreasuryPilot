import { CheckCircle2 } from 'lucide-react';
import { useState } from 'react';

import { KeyValueList } from '@/components/domain/display';
import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert } from '@/components/ui/misc';
import { t } from '@/lib/i18n';

import { useScenario } from './api';
import { fmt, utc } from './format';
import { Usdc } from './usdc';
import { StaleBadge } from './overview-page';
import type { SupplyStatus } from './types';

const supplyLabel = (status: SupplyStatus, dayPlusOne: boolean) => {
  if (status === 'SUBMITTED') return 'Submitted';
  if (status === 'CONFIRMED') return 'Confirmed';
  return dayPlusOne ? 'Ready - waiting for next agent cycle' : 'Not due yet';
};

export function DemoLiquidityPage() {
  const { data } = useScenario();
  const [view, setView] = useState<'allocation' | 'supply' | null>(null);
  if (!data) {
    return (
      <Page title={t('Liquidity')}>
        <ListSkeleton />
      </Page>
    );
  }
  const { state, fixture, allocation: alloc } = data;
  const stale = state.invoiceA.status === 'OUTCOME_UNKNOWN';
  const [, invB, invC] = fixture.invoices;
  const equation = `${fmt(alloc.tBalance)} - ${fmt(alloc.payroll)} - ${fmt(alloc.upcomingBill)} - ${fmt(alloc.floor)} = ${fmt(alloc.surplus)}`;
  return (
    <Page
      title={t('Liquidity')}
      description={t(
        'Revenue, obligations, reserves and the surplus the agent may supply',
      )}
    >
      {state.director.dayPlusOne && (
        <Alert
          tone="info"
          className="mb-4"
          title={t('Next day')}
          data-testid="next-day-banner"
        >
          {t('Scenario time advanced to')} {utc(state.clock)}.
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title={t('Position')}
            description={data.stage ?? ''}
            action={stale ? <StaleBadge /> : undefined}
          />
          <CardContent>
            <KeyValueList
              items={[
                { label: 'T', value: <Usdc value={data.t.balance} /> },
                { label: 'O1', value: <Usdc value={data.o1.balance} /> },
                { label: 'O2', value: <Usdc value={state.ledger.o2} /> },
                { label: t('Aave'), value: <Usdc value={data.aave} /> },
                { label: t('Total'), value: <Usdc value={data.total} /> },
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader title={t('Revenue and obligations')} />
          <CardContent>
            <KeyValueList
              items={[
                {
                  label: t('Revenue'),
                  value: state.director.dayPlusOne ? (
                    <span
                      className="inline-flex items-center gap-2"
                      data-testid="revenue-confirmed"
                    >
                      <Usdc value={state.ledger.revenue} />
                      <Badge tone="success">{t('Confirmed')}</Badge>
                    </span>
                  ) : (
                    '—'
                  ),
                },
                {
                  label: `C · ${invC.number}`,
                  value: state.cApproved ? (
                    <span
                      className="inline-flex items-center gap-2"
                      data-testid="obligation-c"
                    >
                      <Usdc value={invC.amount} />
                      <Badge tone="info">{t('Approved')}</Badge>
                    </span>
                  ) : (
                    '—'
                  ),
                },
                {
                  label: `B · ${invB.number}`,
                  value: (
                    <span className="inline-flex items-center gap-2">
                      <Usdc value={invB.amount} />
                      <Badge tone="neutral">{t('Reserved')}</Badge>
                    </span>
                  ),
                },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader
          title={t('Supply cycle')}
          description={t(
            'The agent supplies only what stays after every reserve',
          )}
          action={
            <span className="flex gap-2">
              <Button size="sm" onClick={() => setView('allocation')}>
                {t('View allocation')}
              </Button>
              <Button size="sm" onClick={() => setView('supply')}>
                {t('View supply plan')}
              </Button>
            </span>
          }
        />
        <CardContent>
          <KeyValueList
            items={[
              {
                label: t('Status'),
                value: (
                  <Badge
                    data-testid="supply-status"
                    tone={
                      state.supply.status === 'CONFIRMED'
                        ? 'success'
                        : state.supply.status === 'SUBMITTED'
                          ? 'info'
                          : 'neutral'
                    }
                  >
                    {t(
                      supplyLabel(
                        state.supply.status,
                        state.director.dayPlusOne,
                      ),
                    )}
                  </Badge>
                ),
              },
              ...(state.supply.reference
                ? [
                    {
                      label: t('Reference'),
                      value: (
                        <span className="num">{state.supply.reference}</span>
                      ),
                    },
                  ]
                : []),
              {
                label: t('Surplus'),
                value: <Usdc value={alloc.surplus} />,
              },
            ]}
          />
        </CardContent>
      </Card>

      <Dialog
        open={view === 'allocation'}
        onOpenChange={(open) => !open && setView(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Allocation')}</DialogTitle>
            <DialogDescription>
              {t('T balance minus payroll, upcoming bill and floor')}
            </DialogDescription>
          </DialogHeader>
          <div data-testid="liquidity-allocation">
            <p
              className="num rounded-md border bg-surface-muted p-3 text-lg font-medium"
              data-testid="allocation-equation"
            >
              {equation}
            </p>
            <KeyValueList
              className="mt-3"
              items={[
                {
                  label: t('T balance'),
                  value: <Usdc value={alloc.tBalance} />,
                },
                {
                  label: t('Payroll B'),
                  value: <Usdc value={alloc.payroll} />,
                },
                {
                  label: t('Upcoming bill C'),
                  value: <Usdc value={alloc.upcomingBill} />,
                },
                { label: t('Floor'), value: <Usdc value={alloc.floor} /> },
                { label: t('Surplus'), value: <Usdc value={alloc.surplus} /> },
              ]}
            />
          </div>
        </DialogContent>
      </Dialog>

      <Dialog
        open={view === 'supply'}
        onOpenChange={(open) => !open && setView(null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t('Supply plan')}</DialogTitle>
            <DialogDescription>{fixture.pool.name}</DialogDescription>
          </DialogHeader>
          <div data-testid="supply-plan">
            <KeyValueList
              items={[
                {
                  label: 'SUPPLY',
                  value: <Usdc value={data.supplyPlan.amount} />,
                },
                {
                  label: t('Exposure after'),
                  value: (
                    <span className="num">
                      {fmt(data.supplyPlan.exposureAfter)} /{' '}
                      {fmt(data.supplyPlan.exposureCap)} USDC
                    </span>
                  ),
                },
              ]}
            />
            <ul className="mt-3 grid gap-1" data-testid="supply-checks">
              {data.supplyPlan.checks.map((check) => (
                <li
                  key={check.id}
                  className="flex items-center gap-2 text-base"
                >
                  <CheckCircle2
                    className={
                      check.pass ? 'size-4 text-success' : 'size-4 text-danger'
                    }
                    aria-hidden="true"
                  />
                  <span>{t(check.label)}</span>
                  <Badge
                    tone={check.pass ? 'success' : 'danger'}
                    className="ml-auto"
                  >
                    {check.pass ? t('Pass') : t('Fail')}
                  </Badge>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-sm text-muted-foreground">
              {t(
                'The fee and risk check is a synthetic assumption. No yield is promised or counted.',
              )}
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
