import { Ban, Download, ScanText, Send, Undo2 } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Group, Panel, Separator } from 'react-resizable-panels';
import { toast } from 'sonner';

import { DocumentViewer } from '@/components/domain/display';
import { WalletActionButton } from '@/components/domain/signing';
import { StatusBadge } from '@/components/domain/status';
import { QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Field, Textarea } from '@/components/ui/input';
import { Alert, Skeleton } from '@/components/ui/misc';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  fetchCancelTx,
  fetchEvidence,
  useConfirmExtraction,
  useConfirmTerms,
  useEditRequest,
  useReportCancelTx,
  useRequest,
  useRequestTransition,
  useTreasuryAsset,
  useVendors,
} from '@/features/requests/api';
import {
  formDefaults,
  RequestForm,
  type RequestFormResult,
} from '@/features/requests/request-form';
import {
  FlagList,
  PaymentOptions,
  RequestFacts,
  RequestTimeline,
  VendorHistory,
} from '@/features/requests/request-parts';
import { useTreasury } from '@/features/treasury/api';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { RequestDetail } from '@/lib/api/types';
import { formatDateTime } from '@/lib/format';
import { t } from '@/lib/i18n';
import { requestStatus } from '@/lib/status';
import { useMediaQuery } from '@/lib/use-media-query';
import { useWallet } from '@/lib/wallet/wallet-context';

/** A reason is required for reject, cancel and request-changes. */
export function ReasonDialog({
  confirmLabel,
  description,
  destructive,
  onConfirm,
  onOpenChange,
  open,
  pending,
  title,
}: {
  confirmLabel: string;
  description: string;
  destructive?: boolean;
  onConfirm: (reason: string) => void;
  onOpenChange: (open: boolean) => void;
  open: boolean;
  pending: boolean;
  title: string;
}) {
  const [reason, setReason] = useState('');
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="sm">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <form
          id="reason-form"
          onSubmit={(event) => {
            event.preventDefault();
            onConfirm(reason.trim());
          }}
        >
          <Field htmlFor="reason" label={t('Reason')}>
            <Textarea
              id="reason"
              required
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </Field>
        </form>
        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>{t('Back')}</Button>
          <Button
            type="submit"
            form="reason-form"
            variant={destructive ? 'danger' : 'primary'}
            loading={pending}
            disabled={!reason.trim()}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** While extraction runs the form stays locked: OCR runs once per document. */
function Extracting({ request }: { request: RequestDetail }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <DocumentViewer document={request.document} />
      <Card>
        <CardContent className="grid gap-4" aria-busy="true">
          <p
            role="status"
            className="flex items-center gap-2 text-base font-medium text-ai-foreground"
          >
            <ScanText className="size-4 animate-pulse" aria-hidden="true" />
            {t('Reading the document…')}
          </p>
          <p className="text-sm text-muted-foreground">
            {t(
              'This usually takes under a minute. The fields unlock when the reading is complete, so nothing you type is overwritten.',
            )}
          </p>
          {Array.from({ length: 5 }, (_, index) => (
            <div key={index}>
              <Skeleton className="h-3 w-24" />
              <Skeleton className="mt-2 h-9 w-full" />
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Draft review (WEB-008): the document on one side, the fields on the other.
 * Saving confirms the extraction and the terms; submitting sends it to approvers.
 */
function DraftEditor({ request }: { request: RequestDetail }) {
  const scope = useOrgScope();
  const asset = useTreasuryAsset(scope.orgId, request.treasuryId);
  const queryClient = useQueryClient();
  const wide = useMediaQuery('(min-width: 1024px)');
  const vendors = useVendors(scope.orgId, request.treasuryId);
  const confirmExtraction = useConfirmExtraction(scope.orgId, request.id);
  const confirmTerms = useConfirmTerms(scope.orgId, request.id);
  const edit = useEditRequest(scope.orgId, request.id);
  const transition = useRequestTransition(
    scope.orgId,
    request.id,
    request.version,
  );
  const [error, setError] = useState<unknown>();
  const [pending, setPending] = useState(false);
  const stale = isApiError(error) && error.status === 412;
  const fromUpload = request.source === 'UPLOAD';

  const saveAndSubmit = async (result: RequestFormResult) => {
    if (!asset) return;
    setError(undefined);
    setPending(true);
    try {
      let version = request.version;
      if (fromUpload) {
        await confirmExtraction.mutateAsync({
          vendor: result.vendorId,
          invoiceNumber: result.invoiceNumber,
          amount: result.amount,
          dueDate: result.dueDate,
          description: result.description,
        });
      } else {
        const edited = await edit.mutateAsync({
          version,
          decimals: asset.decimals,
          issueDate: request.issueDate,
          fields: {
            invoiceNumber: result.invoiceNumber,
            amount: result.amount,
            dueDate: result.dueDate,
            description: result.description,
          },
        });
        version = String(edited.request.version);
      }
      const confirmed = await confirmTerms.mutateAsync({
        version,
        dueDate: result.dueDate,
        earlyPayDate: result.earlyPayDate,
        earlyDiscountBps: result.earlyDiscountBps,
      });
      await transition.mutateAsync({
        action: 'submit',
        version: String(confirmed.request.version),
      });
      toast.success(t('Submitted for approval'));
    } catch (cause) {
      setError(cause);
      // A stale version: reload so the form shows the latest one.
      if (isApiError(cause) && cause.status === 412)
        void queryClient.invalidateQueries({
          queryKey: ['org', scope.orgId, 'requests'],
        });
    } finally {
      setPending(false);
    }
  };

  const form = (
    <Card className="h-full">
      <CardHeader
        title={fromUpload ? t('Check the extracted fields') : t('Draft')}
        description={
          fromUpload
            ? t(
                'Compare each field with the document. Low-confidence values are marked.',
              )
            : t('Edit the draft, then submit it for approval.')
        }
      />
      <CardContent className="grid gap-4">
        {request.status === 'ChangesRequested' && (
          <Alert tone="warning" title={t('Changes requested')}>
            {request.timeline[request.timeline.length - 1]?.label}
          </Alert>
        )}
        {request.injectionWarnings.map((warning) => (
          <Alert
            key={warning}
            tone="warning"
            title={t('Instruction-like text found in the document')}
          >
            {warning}
          </Alert>
        ))}
        <QueryBoundary query={vendors}>
          {({ items }) =>
            asset ? (
              <RequestForm
                key={request.version}
                decimals={asset.decimals}
                vendors={items}
                vendorLocked={!fromUpload}
                extracted={request.fields}
                defaults={formDefaults(request, asset.decimals)}
                onSubmit={(result) => void saveAndSubmit(result)}
              >
                {error !== undefined && (
                  <Alert
                    tone="danger"
                    title={
                      stale
                        ? t('Someone changed this request')
                        : t('The request was not submitted')
                    }
                  >
                    {stale
                      ? t(
                          'This request changed, so the latest version was reloaded. Check it and submit again.',
                        )
                      : errorMessage(error)}
                  </Alert>
                )}
                <div className="flex flex-wrap justify-end gap-2">
                  <Button type="submit" variant="primary" loading={pending}>
                    <Send aria-hidden="true" />
                    {t('Confirm and submit for approval')}
                  </Button>
                </div>
              </RequestForm>
            ) : (
              <Skeleton className="h-64" />
            )
          }
        </QueryBoundary>
      </CardContent>
    </Card>
  );

  if (!request.document) return <div className="mx-auto max-w-2xl">{form}</div>;
  if (!wide) {
    return (
      <div className="grid gap-4">
        <DocumentViewer document={request.document} />
        {form}
      </div>
    );
  }
  return (
    <Group orientation="horizontal" className="min-h-[40rem]">
      <Panel defaultSize="50" minSize="30">
        <DocumentViewer document={request.document} />
      </Panel>
      <Separator
        aria-label={t('Resize panels')}
        className="mx-1.5 w-1 rounded-full bg-border transition-colors hover:bg-border-strong"
      />
      <Panel defaultSize="50" minSize="30">
        {form}
      </Panel>
    </Group>
  );
}

function download(name: string, data: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }),
  );
  const link = Object.assign(document.createElement('a'), {
    href: url,
    download: name,
  });
  link.click();
  URL.revokeObjectURL(url);
}

/** A cancelled request with a live approval must also be cancelled on-chain (M16-D12). */
function CancelOnchainBanner({ request }: { request: RequestDetail }) {
  const scope = useOrgScope();
  const wallet = useWallet();
  const report = useReportCancelTx(scope.orgId, request.id);
  const treasury = useTreasury(scope.orgId, request.treasuryId);
  if (request.cancelOnchain === 'NOT_NEEDED') return null;
  if (request.cancelOnchain === 'CONFIRMED') {
    return (
      <Alert tone="success" title={t('Approval cancelled on-chain')}>
        {t('The signed approval can no longer be used by the module.')}
      </Alert>
    );
  }
  if (request.cancelOnchain === 'PENDING') {
    return (
      <Alert tone="info" title={t('Sent — waiting for the network')}>
        {t('The on-chain cancellation is being confirmed.')}
      </Alert>
    );
  }
  return (
    <Alert tone="danger" title={t('Cancel on-chain to finish')}>
      <p>
        {t(
          'This request is cancelled in TreasuryPilot, but its signed approval is still valid for the contract. Send cancelRequest from an approver wallet to revoke it.',
        )}
      </p>
      <div className="mt-3 max-w-xs">
        <WalletActionButton
          variant="danger"
          chainId={treasury.data?.treasury.chainId ?? 11155111}
          action={async () => {
            const call = await fetchCancelTx(scope.orgId, request.id);
            const txHash = await wallet.sendTransaction(call);
            await report.mutateAsync(txHash);
          }}
        >
          {t('Cancel on-chain')}
        </WalletActionButton>
      </div>
    </Alert>
  );
}

function ReadOnly({ request }: { request: RequestDetail }) {
  const scope = useOrgScope();
  const transition = useRequestTransition(
    scope.orgId,
    request.id,
    request.version,
  );
  const [cancelOpen, setCancelOpen] = useState(false);
  const act = (action: 'withdraw' | 'cancel', reason?: string) =>
    transition.mutate(
      { action, reason },
      {
        onSuccess: () => setCancelOpen(false),
        onError: (error) => toast.error(errorMessage(error)),
      },
    );
  const canCancel =
    scope.can('OPR', 'OWN') &&
    ['AwaitingApproval', 'Approved', 'Scheduled'].includes(request.status);
  const canWithdraw = request.status === 'AwaitingApproval' && scope.can('OPR');
  const canExport = scope.can('FIN', 'AUD', 'ADM');

  return (
    <div className="grid gap-4">
      <CancelOnchainBanner request={request} />
      {request.status === 'AwaitingApproval' && (
        <Alert
          tone="info"
          title={t('Waiting for an approver')}
          action={
            scope.can('APR') && (
              <Button asChild size="sm" variant="primary">
                <Link to={`${scope.base}/approvals/${request.id}`}>
                  {t('Open in approvals')}
                </Link>
              </Button>
            )
          }
        >
          {request.approvalBlocked?.message ??
            t(
              'An approver reviews the flags and signs the approval with their wallet.',
            )}
        </Alert>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-3">
        <div className="grid gap-4 lg:col-span-2">
          <Card>
            <CardHeader title={t('Request')} />
            <CardContent>
              <RequestFacts request={request} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader
              title={t('Payment options')}
              description={t('From the confirmed payment terms.')}
            />
            <CardContent>
              <PaymentOptions request={request} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader title={t('Flags')} />
            <CardContent>
              <FlagList request={request} canAcknowledge={false} />
            </CardContent>
          </Card>
          {request.document && (
            <div className="h-[36rem]">
              <DocumentViewer document={request.document} />
            </div>
          )}
        </div>

        <div className="grid gap-4">
          <Card>
            <CardHeader title={t('Approvals')} />
            <CardContent>
              {request.approvals.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t('No approval signature yet.')}
                </p>
              ) : (
                <ul className="grid gap-2">
                  {request.approvals.map((approval) => (
                    <li key={approval.at} className="text-base">
                      <span className="font-medium">{approval.name}</span>{' '}
                      <span className="text-muted-foreground">
                        {t('signed')} · {formatDateTime(approval.at)} ·{' '}
                        {approval.option === 'EARLY'
                          ? t('prefers early payment')
                          : t('standard payment')}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader title={t('Vendor history')} />
            <CardContent>
              <VendorHistory request={request} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader title={t('Timeline')} />
            <CardContent>
              <RequestTimeline request={request} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader title={t('Revisions')} />
            <ul className="divide-y">
              {request.revisions.map((revision) => (
                <li key={revision.revision} className="px-4 py-2.5 text-sm">
                  <span className="num font-medium">r{revision.revision}</span>{' '}
                  {revision.summary}
                  <span className="block text-xs text-subtle-foreground">
                    {revision.by} · {formatDateTime(revision.at)}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
          {(canWithdraw || canCancel || canExport) && (
            <Card>
              <CardHeader title={t('Actions')} />
              <CardContent className="grid gap-2">
                {canWithdraw && (
                  <Button
                    className="w-full justify-start"
                    loading={transition.isPending}
                    onClick={() => act('withdraw')}
                  >
                    <Undo2 aria-hidden="true" />
                    {t('Withdraw to draft')}
                  </Button>
                )}
                {canCancel && (
                  <Button
                    className="w-full justify-start"
                    variant="danger-outline"
                    onClick={() => setCancelOpen(true)}
                  >
                    <Ban aria-hidden="true" />
                    {t('Cancel request')}
                  </Button>
                )}
                {canExport && (
                  <Button
                    className="w-full justify-start"
                    onClick={() =>
                      void fetchEvidence(scope.orgId, request.id)
                        .then((bundle) =>
                          download(
                            `evidence-${request.invoiceNumber}.json`,
                            bundle,
                          ),
                        )
                        .catch((error: unknown) =>
                          toast.error(errorMessage(error)),
                        )
                    }
                  >
                    <Download aria-hidden="true" />
                    {t('Evidence bundle')}
                  </Button>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      <ReasonDialog
        open={cancelOpen}
        onOpenChange={setCancelOpen}
        destructive
        title={t('Cancel this request?')}
        description={t(
          'It will not be paid. If it already has an approval signature, you will also be asked to cancel it on-chain.',
        )}
        confirmLabel={t('Cancel request')}
        pending={transition.isPending}
        onConfirm={(reason) => act('cancel', reason)}
      />
    </div>
  );
}

export function RequestDetailPage() {
  const scope = useOrgScope();
  const { r: id } = useParams();
  const query = useRequest(scope.orgId, id);
  const request = query.data;
  const editable =
    request && ['Draft', 'ChangesRequested'].includes(request.status);

  return (
    <Page
      width="wide"
      crumbs={[
        { label: t('Requests'), to: `${scope.base}/requests` },
        { label: request?.invoiceNumber ?? '…' },
      ]}
      title={
        request
          ? `${request.invoiceNumber} · ${request.vendorName}`
          : t('Request')
      }
      titleSlot={
        request && <StatusBadge meta={requestStatus(request.status)} />
      }
    >
      <QueryBoundary query={query}>
        {(data) =>
          data.status === 'Extracting' ? (
            <Extracting request={data} />
          ) : editable ? (
            <DraftEditor request={data} />
          ) : (
            <ReadOnly request={data} />
          )
        }
      </QueryBoundary>
    </Page>
  );
}
