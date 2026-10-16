import { CircleCheck, FileSpreadsheet, FileUp, Upload } from 'lucide-react';
import { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import { Link, useNavigate } from 'react-router-dom';

import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
} from '@/components/ui/card';
import { Alert, Skeleton } from '@/components/ui/misc';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  useCreateRequest,
  useIdempotencyKey,
  useImportCsv,
  useTreasuryAsset,
  useUploadInvoice,
  useVendors,
} from '@/features/requests/api';
import { RequestForm } from '@/features/requests/request-form';
import { errorMessage, isApiError } from '@/lib/api/http';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';

function useCrumbs(last: string) {
  const scope = useOrgScope();
  return [
    { label: t('Requests'), to: `${scope.base}/requests` },
    { label: last },
  ];
}

function NeedsTreasury() {
  const scope = useOrgScope();
  return (
    <Alert tone="warning" title={t('Set up a treasury first')}>
      {t('A request is paid from a treasury.')}{' '}
      <Link
        className="font-medium underline"
        to={`${scope.base}/treasuries/new`}
      >
        {t('Start the setup')}
      </Link>
    </Alert>
  );
}

function Dropzone({
  accept,
  busy,
  hint,
  icon: Icon,
  label,
  onFile,
}: {
  accept: Record<string, string[]>;
  busy: boolean;
  hint: string;
  icon: typeof Upload;
  label: string;
  onFile: (file: File) => void;
}) {
  const [rejected, setRejected] = useState('');
  const { getInputProps, getRootProps, isDragActive } = useDropzone({
    accept,
    multiple: false,
    disabled: busy,
    onDrop: (accepted, rejections) => {
      setRejected(
        rejections.length > 0
          ? t('That file type is not supported here. {{hint}}', { hint })
          : '',
      );
      if (accepted[0]) onFile(accepted[0]);
    },
  });
  return (
    <div className="grid gap-3">
      <div
        {...getRootProps()}
        className={cn(
          'grid cursor-pointer place-items-center rounded-lg border-2 border-dashed px-6 py-14 text-center transition-colors',
          isDragActive
            ? 'border-primary bg-primary-muted'
            : 'border-border-strong bg-surface hover:bg-surface-muted',
          busy && 'cursor-progress opacity-60',
        )}
      >
        <input {...getInputProps({ 'aria-label': label })} />
        <div>
          <Icon
            className="mx-auto size-6 text-muted-foreground"
            aria-hidden="true"
          />
          <p className="mt-3 text-lg font-medium">
            {busy ? t('Uploading…') : label}
          </p>
          <p className="mt-1 text-sm text-muted-foreground">{hint}</p>
        </div>
      </div>
      {rejected && <Alert tone="danger">{rejected}</Alert>}
    </div>
  );
}

/** Upload an invoice (WEB-008): the file goes to extraction, then to review. */
export function UploadInvoicePage() {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const upload = useUploadInvoice(scope.orgId);

  return (
    <Page
      width="narrow"
      crumbs={useCrumbs(t('Upload invoice'))}
      title={t('Upload an invoice')}
      description={t(
        'TreasuryPilot reads the vendor, amount, due date and payment terms. You check every field against the document before anything is submitted.',
      )}
    >
      {!scope.treasuryId ? (
        <NeedsTreasury />
      ) : (
        <div className="grid gap-4">
          <Dropzone
            icon={Upload}
            label={t('Drop an invoice here, or click to choose a file')}
            hint={t('PDF, PNG or JPEG, one invoice per file, up to 10 MB.')}
            accept={{
              'application/pdf': ['.pdf'],
              'image/png': ['.png'],
              'image/jpeg': ['.jpg', '.jpeg'],
            }}
            busy={upload.isPending}
            onFile={(file) =>
              upload.mutate(
                { file, treasuryId: scope.treasuryId! },
                {
                  onSuccess: ({ requestId }) =>
                    navigate(`${scope.base}/requests/${requestId}`),
                },
              )
            }
          />
          {upload.isError && (
            <Alert tone="danger" title={t('The invoice was not uploaded')}>
              {errorMessage(upload.error)}
            </Alert>
          )}
          <p className="text-sm text-muted-foreground">
            {t('No document?')}{' '}
            <Link
              className="text-primary underline"
              to={`${scope.base}/requests/new`}
            >
              {t('Enter a request manually')}
            </Link>{' '}
            {t('or')}{' '}
            <Link
              className="text-primary underline"
              to={`${scope.base}/requests/import`}
            >
              {t('import a CSV')}
            </Link>
            .
          </p>
        </div>
      )}
    </Page>
  );
}

/** Manual entry (WEB-007). */
export function NewRequestPage() {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const vendors = useVendors(scope.orgId, scope.treasuryId);
  const create = useCreateRequest(scope.orgId);
  const asset = useTreasuryAsset(scope.orgId, scope.treasuryId);
  const idempotency = useIdempotencyKey();
  const [noPayee, setNoPayee] = useState(false);
  const serverErrors = isApiError(create.error)
    ? Object.fromEntries(
        (create.error.problem.errors ?? []).map((item) => [
          item.field,
          item.message,
        ]),
      )
    : undefined;
  const fieldErrors = noPayee
    ? {
        ...serverErrors,
        vendorId: t('This vendor has no active payee on this treasury.'),
      }
    : serverErrors;

  return (
    <Page
      width="narrow"
      crumbs={useCrumbs(t('New request'))}
      title={t('New payment request')}
      description={t(
        'The request is saved as a draft. You review it once more before submitting it for approval.',
      )}
    >
      {!scope.treasuryId ? (
        <NeedsTreasury />
      ) : (
        <Card>
          <CardContent>
            <QueryBoundary query={vendors}>
              {({ items }) =>
                !asset ? (
                  <Skeleton className="h-64" />
                ) : (
                  <RequestForm
                    vendors={items}
                    decimals={asset.decimals}
                    serverErrors={fieldErrors}
                    onSubmit={(result) => {
                      const vendor = items.find(
                        (v) => v.id === result.vendorId,
                      );
                      setNoPayee(!vendor?.payeeId);
                      if (!vendor?.payeeId) return;
                      const input = {
                        ...result,
                        treasuryId: scope.treasuryId!,
                      };
                      create.mutate(
                        {
                          input,
                          context: {
                            payeeId: vendor.payeeId,
                            assetId: asset.id,
                            decimals: asset.decimals,
                          },
                          idempotencyKey: idempotency.keyFor(
                            JSON.stringify([input, vendor.payeeId]),
                          ),
                        },
                        {
                          onSuccess: ({ request }) => {
                            idempotency.reset();
                            navigate(`${scope.base}/requests/${request.id}`);
                          },
                        },
                      );
                    }}
                  >
                    {create.isError && !fieldErrors?.vendorId && (
                      <Alert tone="danger">{errorMessage(create.error)}</Alert>
                    )}
                    <div className="flex justify-end gap-2">
                      <Button asChild variant="ghost">
                        <Link to={`${scope.base}/requests`}>{t('Cancel')}</Link>
                      </Button>
                      <Button
                        type="submit"
                        variant="primary"
                        loading={create.isPending}
                      >
                        {t('Save draft')}
                      </Button>
                    </div>
                  </RequestForm>
                )
              }
            </QueryBoundary>
          </CardContent>
        </Card>
      )}
    </Page>
  );
}

const csvTemplate =
  'vendor_ref,payee_address,invoice_no,issue_date,due_date,amount,note\nAcurast Cloud,0x0000000000000000000000000000000000000001,AC-2026-120,2026-10-20,2026-11-05,1450.00,Compute\n';

/** CSV import (WEB-020): upload, then a row-by-row result. */
export function ImportCsvPage() {
  const scope = useOrgScope();
  const importCsv = useImportCsv(scope.orgId);
  const result = importCsv.data;

  return (
    <Page
      width="narrow"
      crumbs={useCrumbs(t('Import CSV'))}
      title={t('Import requests from CSV')}
      description={t(
        'Each valid row becomes a draft request. Rows with problems are skipped and listed with the reason, so you can fix the file and import again.',
      )}
    >
      {!scope.treasuryId ? (
        <NeedsTreasury />
      ) : (
        <div className="grid gap-4">
          <Card>
            <CardHeader
              title={t('File format')}
              description={t(
                'First row: vendor_ref, payee_address, invoice_no, issue_date, due_date, amount, note (optional)',
              )}
              action={
                <Button asChild size="sm">
                  <a
                    href={`data:text/csv;charset=utf-8,${encodeURIComponent(csvTemplate)}`}
                    download="treasurypilot-requests-template.csv"
                  >
                    {t('Download template')}
                  </a>
                </Button>
              }
            />
            <CardContent className="text-sm text-muted-foreground">
              <ul className="list-disc space-y-1 pl-5">
                <li>
                  {t(
                    'vendor_ref must match an existing vendor, and payee_address its registered payee.',
                  )}
                </li>
                <li>
                  {t(
                    'amount is in USDC with up to 6 decimals, for example 1450.00.',
                  )}
                </li>
                <li>{t('issue_date and due_date are YYYY-MM-DD.')}</li>
              </ul>
            </CardContent>
          </Card>

          <Dropzone
            icon={FileUp}
            label={t('Drop a CSV file here, or click to choose one')}
            hint={t('One .csv file.')}
            accept={{ 'text/csv': ['.csv'] }}
            busy={importCsv.isPending}
            onFile={(file) =>
              importCsv.mutate({ file, treasuryId: scope.treasuryId! })
            }
          />

          {importCsv.isError && (
            <Alert tone="danger" title={t('The file was not imported')}>
              {errorMessage(importCsv.error)}
            </Alert>
          )}

          {result && (
            <Card>
              <CardHeader
                title={t('Import result')}
                description={t(
                  '{{created}} drafts created, {{errors}} rows skipped',
                  {
                    created: result.created.length,
                    errors: result.errors.length,
                  },
                )}
              />
              {result.created.length > 0 && (
                <ul className="divide-y border-b">
                  {result.created.map((row) => (
                    <li
                      key={row.requestId}
                      className="flex items-center gap-2 px-4 py-2 text-base"
                    >
                      <CircleCheck
                        className="size-4 text-success"
                        aria-hidden="true"
                      />
                      <span className="text-muted-foreground">
                        {t('Row {{row}}', { row: row.row })}
                      </span>
                      <Link
                        className="num font-medium text-primary hover:underline"
                        to={`${scope.base}/requests/${row.requestId}`}
                      >
                        {row.invoiceNumber}
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
              {result.errors.length > 0 && (
                <Table>
                  <TableHeader>
                    <tr>
                      <TableHead>{t('Row')}</TableHead>
                      <TableHead>{t('Problem')}</TableHead>
                      <TableHead>{t('Code')}</TableHead>
                    </tr>
                  </TableHeader>
                  <TableBody>
                    {result.errors.map((row) => (
                      <TableRow key={row.row}>
                        <TableCell className="num">{row.row}</TableCell>
                        <TableCell>{row.message}</TableCell>
                        <TableCell className="num text-xs text-muted-foreground">
                          {row.code}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              <CardFooter>
                <Button asChild variant="primary">
                  <Link to={`${scope.base}/requests`}>
                    <FileSpreadsheet aria-hidden="true" />
                    {t('Go to requests')}
                  </Link>
                </Button>
              </CardFooter>
            </Card>
          )}
        </div>
      )}
    </Page>
  );
}
