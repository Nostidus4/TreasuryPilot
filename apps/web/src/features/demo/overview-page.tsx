import { ClipboardList } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  SheetContent,
} from '@/components/ui/dialog';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { KeyValueList } from '@/components/domain/display';
import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { useOrgScope } from '@/features/orgs/org-scope';
import { t } from '@/lib/i18n';

import { useScenario } from './api';
import { fmt, invoiceLabel, invoiceTone, utc } from './format';
import { Usdc } from './usdc';

export function StaleBadge() {
  return (
    <Badge tone="warning" data-testid="refresh-pending">
      {t('Refresh pending')}
    </Badge>
  );
}

export function DemoOverviewPage() {
  const scope = useOrgScope();
  const { data } = useScenario();
  const [sheet, setSheet] = useState<'T' | 'O1' | null>(null);
  if (!data) {
    return (
      <Page title={t('Overview')}>
        <ListSkeleton />
      </Page>
    );
  }
  const { state, fixture } = data;
  const a = state.invoiceA;
  const stale = a.status === 'OUTCOME_UNKNOWN';
  const payroll = fixture.invoices[1];
  const upcoming = fixture.invoices[2];
  const taskOpen =
    a.status === 'ABSENT' || a.status === 'EXTRACTING' || a.status === 'DRAFT';

  return (
    <Page
      title={t('Overview')}
      description={`${fixture.organization.name} · ${fixture.organization.businessType}`}
      titleSlot={
        <Badge tone="neutral">
          {t('Snapshot')} {utc(state.clock)}
        </Badge>
      }
    >
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader
            title={t('Safes')}
            description={t('Balances, protected amounts and what is free')}
            action={stale ? <StaleBadge /> : undefined}
          />
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{t('Safe')}</TableHead>
                  <TableHead className="text-right">{t('Balance')}</TableHead>
                  <TableHead className="text-right">{t('Protected')}</TableHead>
                  <TableHead className="text-right">{t('Free')}</TableHead>
                  <TableHead />
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow data-testid="row-t">
                  <TableCell className="font-medium">
                    {fixture.accounts[0].name}
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value={data.t.balance} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc
                      value={(
                        BigInt(data.t.balance) - BigInt(data.t.free)
                      ).toString()}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value={data.t.free} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button size="sm" onClick={() => setSheet('T')}>
                      {t('View breakdown')}
                    </Button>
                  </TableCell>
                </TableRow>
                <TableRow data-testid="row-o1">
                  <TableCell className="font-medium">
                    {fixture.accounts[1].name}
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value={data.o1.balance} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc
                      value={(
                        BigInt(data.o1.balance) - BigInt(data.o1.spendable)
                      ).toString()}
                    />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value={data.o1.spendable} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => setSheet('O1')}
                    >
                      {t('View O1 details')}
                    </Button>
                  </TableCell>
                </TableRow>
                <TableRow data-testid="row-o2">
                  <TableCell className="font-medium">
                    {fixture.accounts[2].name}
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value={state.ledger.o2} />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value="0" />
                  </TableCell>
                  <TableCell className="text-right">
                    <Usdc value="0" />
                  </TableCell>
                  <TableCell />
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader
            title={t('Aave position')}
            description={fixture.pool.name}
          />
          <CardContent>
            <KeyValueList
              items={[
                {
                  label: t('Supplied'),
                  value: <Usdc value={data.aave} />,
                },
                {
                  label: t('Exposure cap'),
                  value: <Usdc value={fixture.mandate.maxPoolExposure} />,
                },
                {
                  label: t('Cash on wallets'),
                  value: <Usdc value={data.cash} />,
                },
                {
                  label: t('Total (cash + Aave)'),
                  value: <Usdc value={data.total} />,
                },
                { label: t('Borrowed'), value: t('None') },
              ]}
            />
          </CardContent>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title={t('Scheduled obligations')}
            description={t('Reserved at T until they are paid')}
          />
          <CardContent>
            <KeyValueList
              items={[
                {
                  label: (
                    <span>
                      B · {payroll.number}
                      <span className="block text-xs text-subtle-foreground">
                        {t('Due')} {utc(payroll.dueAt)} · {t('not paid early')}
                      </span>
                    </span>
                  ),
                  value: (
                    <span
                      className="flex flex-col items-end gap-1"
                      data-testid="obligation-b"
                    >
                      <Usdc value={payroll.amount} />
                      <span className="flex gap-1">
                        <Badge tone="info">{t('Approved / Scheduled')}</Badge>
                        <Badge tone="neutral">{t('Reserved at T')}</Badge>
                      </span>
                    </span>
                  ),
                },
                ...(state.cApproved
                  ? [
                      {
                        label: (
                          <span>
                            C · {upcoming.number}
                            <span className="block text-xs text-subtle-foreground">
                              {t('Due')} {utc(upcoming.dueAt)}
                            </span>
                          </span>
                        ),
                        value: (
                          <span className="flex flex-col items-end gap-1">
                            <Usdc value={upcoming.amount} />
                            <span className="flex gap-1">
                              <Badge tone="info">
                                {t('Approved / Scheduled')}
                              </Badge>
                              <Badge tone="neutral">{t('Reserved at T')}</Badge>
                            </span>
                          </span>
                        ),
                      },
                    ]
                  : []),
                ...(a.status !== 'ABSENT'
                  ? [
                      {
                        label: (
                          <span>
                            A · {fixture.invoices[0].number}
                            <span className="block text-xs text-subtle-foreground">
                              {t('Early amount')}{' '}
                              {fmt(fixture.invoices[0].earlyAmount)} USDC
                            </span>
                          </span>
                        ),
                        value: (
                          <Link to={`${scope.base}/requests/inv-cloud-042`}>
                            <Badge tone={invoiceTone(a.status)}>
                              {t(invoiceLabel[a.status])}
                            </Badge>
                          </Link>
                        ),
                      },
                    ]
                  : []),
              ]}
            />
          </CardContent>
        </Card>

        <Card>
          <CardHeader title={t('Tasks')} />
          <CardContent>
            <div
              className="flex items-center gap-3"
              data-testid="task-review-cloud-bill"
            >
              <ClipboardList
                className="size-5 text-muted-foreground"
                aria-hidden="true"
              />
              <div className="min-w-0 flex-1">
                <p className="text-base font-medium">
                  {t('Review cloud bill')}
                </p>
                <p className="text-sm text-muted-foreground">
                  {t(
                    'A document to review. It is not a spending authorization.',
                  )}
                </p>
              </div>
              {taskOpen ? (
                <Button size="sm" asChild>
                  <Link to={`${scope.base}/requests`}>
                    {t('Open invoices')}
                  </Link>
                </Button>
              ) : (
                <Badge tone="success">{t('Submitted')}</Badge>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog
        open={sheet === 'T'}
        onOpenChange={(open) => !open && setSheet(null)}
      >
        <SheetContent width="md" aria-describedby={undefined}>
          <div className="border-b p-4 pr-12">
            <DialogTitle className="text-lg font-semibold">
              {fixture.accounts[0].name}
            </DialogTitle>
            <DialogDescription className="mt-1 text-sm text-muted-foreground">
              {t('What is protected at T, and what is free')}
            </DialogDescription>
          </div>
          <div className="p-4" data-testid="treasury-t-breakdown">
            <KeyValueList
              items={[
                {
                  label: t('Balance'),
                  value: <Usdc value={data.t.balance} />,
                },
                {
                  label: t('Payroll reserve'),
                  hint: `${payroll.number}`,
                  value: <Usdc value={data.t.payrollReserve} />,
                },
                { label: t('Floor'), value: <Usdc value={data.t.floor} /> },
                ...(state.cApproved
                  ? [
                      {
                        label: t('Upcoming bill reserve'),
                        hint: upcoming.number,
                        value: <Usdc value={data.t.upcomingBillReserve} />,
                      },
                    ]
                  : []),
                ...(BigInt(data.t.fundingHoldA) > 0n
                  ? [
                      {
                        label: t('Funding hold: invoice A'),
                        value: <Usdc value={data.t.fundingHoldA} />,
                      },
                    ]
                  : []),
                {
                  label:
                    a.status === 'ABSENT' ||
                    a.status === 'EXTRACTING' ||
                    a.status === 'DRAFT' ||
                    a.status === 'AWAITING_APPROVAL' ||
                    a.status === 'APPROVED' ||
                    a.status === 'READY_WAITING_WINDOW'
                      ? t('Free before A')
                      : t('Free (uncommitted)'),
                  value: <Usdc value={data.t.free} />,
                },
              ]}
            />
            {stale && (
              <p className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
                <StaleBadge />
                {t(
                  'Last verified balance. The payment outcome is not verified yet.',
                )}
              </p>
            )}
          </div>
        </SheetContent>
      </Dialog>

      <Dialog
        open={sheet === 'O1'}
        onOpenChange={(open) => !open && setSheet(null)}
      >
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>{fixture.accounts[1].name}</DialogTitle>
            <DialogDescription>
              {t('Buffer and what O1 can spend')}
            </DialogDescription>
          </DialogHeader>
          <div data-testid="o1-detail">
            <KeyValueList
              items={[
                {
                  label: t('Balance'),
                  value: <Usdc value={data.o1.balance} />,
                },
                { label: t('Buffer'), value: <Usdc value={data.o1.buffer} /> },
                ...(BigInt(data.o1.executionHold) > 0n
                  ? [
                      {
                        label: t('Execution hold: invoice A'),
                        value: <Usdc value={data.o1.executionHold} />,
                      },
                    ]
                  : []),
                {
                  label: t('Spendable'),
                  value: <Usdc value={data.o1.spendable} />,
                },
              ]}
            />
          </div>
        </DialogContent>
      </Dialog>
    </Page>
  );
}
