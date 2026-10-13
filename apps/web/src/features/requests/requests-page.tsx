import type { ColumnDef } from '@tanstack/react-table';
import { FileSpreadsheet, FileText, Flag, Plus, Upload } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { DataTable } from '@/components/data-table';
import { Amount, AmountHeader } from '@/components/domain/amount';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useRequests } from '@/features/requests/api';
import type { PaymentRequest, RequestStatus } from '@/lib/api/types';
import { dueLabel, formatDate } from '@/lib/format';
import { t } from '@/lib/i18n';
import { requestStatus } from '@/lib/status';
import { cn } from '@/lib/utils';

const groups: Array<{
  value: string;
  label: string;
  statuses: RequestStatus[];
}> = [
  {
    value: 'open',
    label: 'Open',
    statuses: [
      'Extracting',
      'Draft',
      'ChangesRequested',
      'AwaitingApproval',
      'Approved',
      'Scheduled',
      'InFlight',
    ],
  },
  {
    value: 'drafts',
    label: 'Drafts',
    statuses: ['Extracting', 'Draft', 'ChangesRequested'],
  },
  {
    value: 'awaiting',
    label: 'Awaiting approval',
    statuses: ['AwaitingApproval'],
  },
  {
    value: 'approved',
    label: 'Approved',
    statuses: ['Approved', 'Scheduled', 'InFlight'],
  },
  { value: 'paid', label: 'Paid', statuses: ['Paid'] },
  {
    value: 'closed',
    label: 'Rejected or cancelled',
    statuses: ['Rejected', 'Cancelled'],
  },
  { value: 'all', label: 'All', statuses: [] },
];

const sourceLabel = { MANUAL: 'Manual', UPLOAD: 'Upload', CSV: 'CSV' } as const;

function DueCell({ request }: { request: PaymentRequest }) {
  const settled = ['Paid', 'Rejected', 'Cancelled'].includes(request.status);
  const due = dueLabel(request.dueDate);
  return (
    <div>
      <p className="whitespace-nowrap">{formatDate(request.dueDate)}</p>
      {!settled && (
        <p
          className={cn(
            'text-xs',
            due.overdue
              ? 'font-medium text-danger-foreground'
              : due.soon
                ? 'text-warning-foreground'
                : 'text-muted-foreground',
          )}
        >
          {due.text}
        </p>
      )}
    </div>
  );
}

/** Requests list (WEB-007). */
export function RequestsPage() {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const query = useRequests(scope.orgId);
  const [group, setGroup] = useState('open');

  const columns = useMemo<Array<ColumnDef<PaymentRequest, unknown>>>(
    () => [
      {
        id: 'invoice',
        header: t('Invoice'),
        accessorFn: (row) => `${row.invoiceNumber} ${row.vendorName}`,
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="num font-medium">{row.original.invoiceNumber}</p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.vendorName}
            </p>
          </div>
        ),
      },
      {
        id: 'amount',
        header: () => <AmountHeader />,
        accessorFn: (row) => Number(BigInt(row.amount) / 10000n),
        meta: { align: 'right' },
        cell: ({ row }) => (
          <Amount value={row.original.amount} context="column" />
        ),
      },
      {
        id: 'due',
        header: t('Due'),
        accessorKey: 'dueDate',
        cell: ({ row }) => <DueCell request={row.original} />,
      },
      {
        id: 'status',
        header: t('Status'),
        accessorKey: 'status',
        cell: ({ row }) => (
          <div className="flex flex-wrap items-center gap-1.5">
            <StatusBadge meta={requestStatus(row.original.status)} />
            {row.original.openFlags > 0 && (
              <Badge
                tone={row.original.highFlagsUnacked > 0 ? 'danger' : 'warning'}
              >
                <Flag aria-hidden="true" />
                {t('{{count}} flags', { count: row.original.openFlags })}
              </Badge>
            )}
          </div>
        ),
      },
      {
        id: 'source',
        header: t('Source'),
        accessorKey: 'source',
        meta: { hideOnMobile: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {t(sourceLabel[row.original.source])}
          </span>
        ),
      },
      {
        id: 'createdBy',
        header: t('Created by'),
        accessorFn: (row) => row.createdBy.name,
        meta: { hideOnMobile: true },
        cell: ({ row }) => (
          <span className="text-muted-foreground">
            {row.original.createdBy.name}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <Page
      width="wide"
      title={t('Requests')}
      description={t(
        'Every invoice to pay starts as a request. A request is paid only after an approver signs it and the policy engine allows it.',
      )}
      actions={
        scope.can('OPR', 'ADM') && (
          <>
            <Button asChild>
              <Link to={`${scope.base}/requests/import`}>
                <FileSpreadsheet aria-hidden="true" />
                {t('Import CSV')}
              </Link>
            </Button>
            <Button asChild>
              <Link to={`${scope.base}/requests/new`}>
                <Plus aria-hidden="true" />
                {t('New request')}
              </Link>
            </Button>
            <Button asChild variant="primary">
              <Link to={`${scope.base}/requests/upload`}>
                <Upload aria-hidden="true" />
                {t('Upload invoice')}
              </Link>
            </Button>
          </>
        )
      }
    >
      <Card className="overflow-hidden">
        <QueryBoundary query={query}>
          {({ items }) => {
            const active = groups.find((item) => item.value === group)!;
            const rows = items.filter(
              (item) =>
                active.statuses.length === 0 ||
                active.statuses.includes(item.status),
            );
            return (
              <DataTable
                columns={columns}
                data={rows}
                getRowId={(row) => row.id}
                rowLabel={(row) =>
                  t('Open request {{invoice}}', { invoice: row.invoiceNumber })
                }
                onRowClick={(row) =>
                  navigate(`${scope.base}/requests/${row.id}`)
                }
                searchPlaceholder={t('Search vendor or invoice number')}
                filter={{
                  value: group,
                  onChange: setGroup,
                  options: groups.map((item) => ({
                    value: item.value,
                    label: t(item.label),
                    count: items.filter(
                      (request) =>
                        item.statuses.length === 0 ||
                        item.statuses.includes(request.status),
                    ).length,
                  })),
                }}
                empty={
                  items.length === 0 ? (
                    <EmptyState
                      icon={FileText}
                      title={t('No payment requests yet')}
                      description={t(
                        'Upload an invoice and TreasuryPilot reads the vendor, amount, due date and payment terms for you to confirm.',
                      )}
                      action={
                        <Button asChild variant="primary">
                          <Link to={`${scope.base}/requests/upload`}>
                            <Upload aria-hidden="true" />
                            {t('Upload invoice')}
                          </Link>
                        </Button>
                      }
                    />
                  ) : (
                    <EmptyState
                      title={t('Nothing matches')}
                      description={t(
                        'No request matches this filter and search. Try “All”, or clear the search.',
                      )}
                      action={
                        <Button onClick={() => setGroup('all')}>
                          {t('Show all requests')}
                        </Button>
                      }
                    />
                  )
                }
              />
            );
          }}
        </QueryBoundary>
      </Card>
    </Page>
  );
}
