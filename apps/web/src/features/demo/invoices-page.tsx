import { Upload } from 'lucide-react';
import { useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { ListSkeleton } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert } from '@/components/ui/misc';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useOrgScope } from '@/features/orgs/org-scope';
import { t } from '@/lib/i18n';

import { actionError, useDemoAction, useScenario } from './api';
import { invoiceLabel, invoiceTone, utc } from './format';
import { Usdc } from './usdc';

export function DemoInvoicesPage() {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const { data } = useScenario();
  const upload = useDemoAction<{ fileName: string }>('/demo/invoices/upload');
  const [open, setOpen] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  if (!data) {
    return (
      <Page title={t('Invoices')}>
        <ListSkeleton />
      </Page>
    );
  }
  const { state, fixture } = data;
  const a = state.invoiceA;
  const [invA, invB, invC] = fixture.invoices;
  const finance = state.role === 'FINANCE';

  const rows: Array<{
    id: string;
    number: string;
    payee: string;
    amount: string;
    due: string;
    status: React.ReactNode;
  }> = [
    {
      id: invB.id,
      number: invB.number,
      payee: fixture.payees[1].name,
      amount: invB.amount,
      due: invB.dueAt,
      status: <Badge tone="info">{t('Approved / Scheduled')}</Badge>,
    },
    ...(a.status !== 'ABSENT'
      ? [
          {
            id: invA.id,
            number: invA.number,
            payee: fixture.payees[0].name,
            amount: invA.earlyAmount,
            due: invA.dueAt,
            status: (
              <Badge tone={invoiceTone(a.status)}>
                {t(invoiceLabel[a.status])}
              </Badge>
            ),
          },
        ]
      : []),
    ...(state.cApproved
      ? [
          {
            id: invC.id,
            number: invC.number,
            payee: fixture.payees[2].name,
            amount: invC.amount,
            due: invC.dueAt,
            status: <Badge tone="info">{t('Approved / Scheduled')}</Badge>,
          },
        ]
      : []),
    ...(state.invoiceX.present
      ? [
          {
            id: fixture.securityScenario.invoiceId,
            number: fixture.securityScenario.number,
            payee: fixture.securityScenario.recipientAlias,
            amount: fixture.securityScenario.amount,
            due: '',
            status:
              state.invoiceX.status === 'BLOCKED_UNKNOWN_RECIPIENT' ? (
                <Badge tone="danger">BLOCKED_UNKNOWN_RECIPIENT</Badge>
              ) : (
                <Badge tone="warning">{t('Flagged review')}</Badge>
              ),
          },
        ]
      : []),
  ];

  const onFile = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(
      { fileName: file.name },
      {
        onSuccess: () => {
          setOpen(false);
          navigate(`${scope.base}/requests/${invA.id}`);
        },
      },
    );
  };

  return (
    <Page
      title={t('Invoices')}
      description={t('Invoices and approved obligations')}
      actions={
        finance && (
          <Button
            variant="primary"
            data-testid="invoice-upload"
            onClick={() => {
              upload.reset();
              setOpen(true);
            }}
          >
            <Upload aria-hidden="true" />
            {t('Upload invoice')}
          </Button>
        )
      }
    >
      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t('Invoice')}</TableHead>
              <TableHead>{t('Payee')}</TableHead>
              <TableHead className="text-right">{t('Amount')}</TableHead>
              <TableHead>{t('Due')}</TableHead>
              <TableHead>{t('Status')}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} data-testid={`invoice-row-${row.id}`}>
                <TableCell className="font-medium">
                  <Link
                    className="text-primary hover:underline"
                    to={`${scope.base}/requests/${row.id}`}
                  >
                    {row.number}
                  </Link>
                </TableCell>
                <TableCell>{row.payee}</TableCell>
                <TableCell className="text-right">
                  <Usdc value={row.amount} />
                </TableCell>
                <TableCell>{row.due ? utc(row.due) : '—'}</TableCell>
                <TableCell>{row.status}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent size="sm">
          <DialogHeader>
            <DialogTitle>{t('Upload invoice')}</DialogTitle>
            <DialogDescription>
              {t(
                'Demo mode reads one recorded invoice: INV-CLOUD-042.pdf. Other files are unsupported.',
              )}
            </DialogDescription>
          </DialogHeader>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            data-testid="invoice-upload-input"
            aria-label={t('Invoice file')}
            className="block w-full text-base file:mr-3 file:rounded-md file:border file:bg-surface file:px-3 file:py-1.5"
            onChange={(event) => {
              onFile(event.target.files?.[0]);
              event.target.value = '';
            }}
          />
          {upload.isError && (
            <Alert tone="danger" data-testid="invoice-upload-error">
              {actionError(upload.error)}
            </Alert>
          )}
        </DialogContent>
      </Dialog>
    </Page>
  );
}
