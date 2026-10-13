import type { ColumnDef } from '@tanstack/react-table';
import { ArrowLeftRight, Download, ExternalLink } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { DataTable } from '@/components/data-table';
import { Amount, AmountHeader } from '@/components/domain/amount';
import { TxHash } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogDescription,
  DialogTitle,
  SheetContent,
} from '@/components/ui/dialog';
import { Field, Textarea } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import {
  reconciliationExportUrl,
  useReconcile,
  useReconciliations,
} from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { fetchEvidence } from '@/features/requests/api';
import { errorMessage } from '@/lib/api/http';
import type { Reconciliation } from '@/lib/api/types';
import { formatDateTime, shortHash } from '@/lib/format';
import { t } from '@/lib/i18n';

const statusTone = {
  Unmatched: 'warning',
  Matched: 'success',
  Discrepancy: 'danger',
} as const;

const EAS_EXPLORER = 'https://sepolia.easscan.org/attestation/view';

function saveFile(name: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  Object.assign(document.createElement('a'), {
    href: url,
    download: name,
  }).click();
  URL.revokeObjectURL(url);
}

function DetailSheet({
  item,
  onClose,
}: {
  item: Reconciliation | null;
  onClose: () => void;
}) {
  const scope = useOrgScope();
  const reconcile = useReconcile(scope.orgId);
  const [note, setNote] = useState('');
  const canDecide = scope.can('FIN');

  const decide = (outcome: 'match' | 'discrepancy') => {
    if (!item) return;
    reconcile.mutate(
      { id: item.id, outcome, note },
      {
        onSuccess: () => {
          toast.success(
            outcome === 'match'
              ? t('Marked as matched')
              : t('Discrepancy flagged'),
          );
          setNote('');
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open={item !== null}
      onOpenChange={(open) => {
        if (!open) {
          reconcile.reset();
          onClose();
        }
      }}
    >
      <SheetContent width="md">
        {item && (
          <>
            <header className="border-b px-4 py-3 pr-12">
              <DialogTitle className="text-lg font-semibold">
                <span className="num">{item.invoiceNumber}</span> ·{' '}
                {item.vendorName}
              </DialogTitle>
              <DialogDescription className="text-sm text-muted-foreground">
                {t(
                  'Compare the on-chain payment with your books, then record the result.',
                )}
              </DialogDescription>
            </header>
            <div className="grid min-h-0 flex-1 content-start gap-4 overflow-y-auto p-4">
              <KeyValueList
                items={[
                  {
                    label: t('Status'),
                    value: (
                      <Badge tone={statusTone[item.status]}>
                        {t(item.status)}
                      </Badge>
                    ),
                  },
                  {
                    label: t('Paid amount'),
                    value: <Amount value={item.amount} />,
                  },
                  { label: t('Paid at'), value: formatDateTime(item.paidAt) },
                  {
                    label: t('Transaction'),
                    value: <TxHash hash={item.txHash} />,
                  },
                  {
                    label: t('Payment receipt (EAS)'),
                    value: item.easUid ? (
                      <a
                        href={`${EAS_EXPLORER}/${item.easUid}`}
                        target="_blank"
                        rel="noreferrer"
                        className="num inline-flex items-center gap-1 text-sm text-primary hover:underline"
                      >
                        {shortHash(item.easUid)}
                        <ExternalLink className="size-3" aria-hidden="true" />
                      </a>
                    ) : (
                      <span className="text-muted-foreground">
                        {t('Not attested yet')}
                      </span>
                    ),
                  },
                  {
                    label: t('Request'),
                    value: (
                      <Link
                        className="text-primary hover:underline"
                        to={`${scope.base}/requests/${item.requestId}`}
                      >
                        {t('Open request')}
                      </Link>
                    ),
                  },
                ]}
              />
              {item.note && (
                <Alert tone="neutral" title={t('Note')}>
                  {item.note}
                </Alert>
              )}
              {!item.evidenceComplete && (
                <Alert tone="warning" title={t('Evidence is incomplete')}>
                  {t(
                    'The payment receipt attestation is missing, so this payment cannot be marked as matched yet.',
                  )}
                </Alert>
              )}
              <Button
                className="justify-self-start"
                onClick={() =>
                  void fetchEvidence(scope.orgId, item.requestId)
                    .then((bundle) =>
                      saveFile(
                        `evidence-${item.invoiceNumber}.json`,
                        JSON.stringify(bundle, null, 2),
                        'application/json',
                      ),
                    )
                    .catch((error: unknown) => toast.error(errorMessage(error)))
                }
              >
                <Download aria-hidden="true" />
                {t('Download evidence bundle')}
              </Button>

              {canDecide ? (
                <div className="grid gap-3 border-t pt-4">
                  <Field
                    htmlFor="reconcile-note"
                    label={t('Note')}
                    hint={t('Required for a discrepancy.')}
                    error={
                      reconcile.isError
                        ? errorMessage(reconcile.error)
                        : undefined
                    }
                  >
                    <Textarea
                      id="reconcile-note"
                      value={note}
                      onChange={(event) => setNote(event.target.value)}
                    />
                  </Field>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="primary"
                      loading={
                        reconcile.isPending &&
                        reconcile.variables?.outcome === 'match'
                      }
                      disabled={!item.evidenceComplete}
                      onClick={() => decide('match')}
                    >
                      {t('Mark as matched')}
                    </Button>
                    <Button
                      variant="danger-outline"
                      loading={
                        reconcile.isPending &&
                        reconcile.variables?.outcome === 'discrepancy'
                      }
                      disabled={!note.trim()}
                      onClick={() => decide('discrepancy')}
                    >
                      {t('Flag discrepancy')}
                    </Button>
                  </div>
                </div>
              ) : (
                <Alert tone="neutral">
                  {t('Only Finance can record a reconciliation result.')}
                </Alert>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Dialog>
  );
}

/** Reconciliation (WEB-014): match on-chain payments to the books, export, evidence. */
export function ReconciliationPage() {
  const scope = useOrgScope();
  const query = useReconciliations(scope.orgId);
  const [filter, setFilter] = useState('Unmatched');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const columns = useMemo<Array<ColumnDef<Reconciliation, unknown>>>(
    () => [
      {
        id: 'invoice',
        header: t('Invoice'),
        accessorFn: (row) => `${row.invoiceNumber} ${row.vendorName}`,
        cell: ({ row }) => (
          <div>
            <p className="num font-medium">{row.original.invoiceNumber}</p>
            <p className="text-xs text-muted-foreground">
              {row.original.vendorName}
            </p>
          </div>
        ),
      },
      {
        id: 'amount',
        header: () => <AmountHeader label="Paid" />,
        accessorFn: (row) => Number(BigInt(row.amount) / 10000n),
        meta: { align: 'right' },
        cell: ({ row }) => (
          <Amount value={row.original.amount} context="column" />
        ),
      },
      {
        id: 'paidAt',
        header: t('Paid at'),
        accessorKey: 'paidAt',
        meta: { hideOnMobile: true },
        cell: ({ row }) => formatDateTime(row.original.paidAt),
      },
      {
        id: 'tx',
        header: t('Transaction'),
        enableSorting: false,
        meta: { hideOnMobile: true },
        cell: ({ row }) => <TxHash hash={row.original.txHash} />,
      },
      {
        id: 'status',
        header: t('Status'),
        accessorKey: 'status',
        cell: ({ row }) => (
          <div className="flex flex-wrap gap-1.5">
            <Badge tone={statusTone[row.original.status]}>
              {t(row.original.status)}
            </Badge>
            {!row.original.evidenceComplete && (
              <Badge tone="warning">{t('Evidence incomplete')}</Badge>
            )}
          </div>
        ),
      },
    ],
    [],
  );

  const exportCsv = async () => {
    setExporting(true);
    try {
      const response = await fetch(reconciliationExportUrl(scope.orgId), {
        credentials: 'include',
      });
      if (!response.ok) throw new Error(t('The export could not be created.'));
      saveFile('reconciliation.csv', await response.text(), 'text/csv');
    } catch (error) {
      toast.error(errorMessage(error));
    } finally {
      setExporting(false);
    }
  };

  return (
    <Page
      width="wide"
      title={t('Reconciliation')}
      description={t(
        'Every verified payment, ready to match against your books. Each one carries an evidence bundle and an on-chain receipt.',
      )}
      actions={
        <Button loading={exporting} onClick={() => void exportCsv()}>
          <Download aria-hidden="true" />
          {t('Export CSV')}
        </Button>
      }
    >
      <Card className="overflow-hidden">
        <QueryBoundary query={query}>
          {({ items }) => {
            const rows = items.filter(
              (item) => filter === 'all' || item.status === filter,
            );
            return (
              <>
                <DataTable
                  columns={columns}
                  data={rows}
                  getRowId={(row) => row.id}
                  selectedId={selectedId ?? undefined}
                  onRowClick={(row) => setSelectedId(row.id)}
                  rowLabel={(row) =>
                    t('Open payment {{invoice}}', {
                      invoice: row.invoiceNumber,
                    })
                  }
                  searchPlaceholder={t('Search vendor or invoice number')}
                  filter={{
                    value: filter,
                    onChange: setFilter,
                    options: [
                      ...(['Unmatched', 'Matched', 'Discrepancy'] as const).map(
                        (status) => ({
                          value: status,
                          label: t(status),
                          count: items.filter((item) => item.status === status)
                            .length,
                        }),
                      ),
                      { value: 'all', label: t('All'), count: items.length },
                    ],
                  }}
                  empty={
                    items.length === 0 ? (
                      <EmptyState
                        icon={ArrowLeftRight}
                        title={t('No payments to reconcile')}
                        description={t(
                          'A payment appears here once it is verified on-chain.',
                        )}
                      />
                    ) : (
                      <EmptyState
                        title={t('Nothing in this view')}
                        description={t(
                          'No payment has this status. Try another filter.',
                        )}
                        action={
                          <Button onClick={() => setFilter('all')}>
                            {t('Show all')}
                          </Button>
                        }
                      />
                    )
                  }
                />
                <DetailSheet
                  item={items.find((item) => item.id === selectedId) ?? null}
                  onClose={() => setSelectedId(null)}
                />
              </>
            );
          }}
        </QueryBoundary>
      </Card>
    </Page>
  );
}
