import { ClipboardCheck, Flag, PenLine, Users } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Amount } from '@/components/domain/amount';
import { DocumentViewer } from '@/components/domain/display';
import {
  TypedDataTable,
  WalletActionButton,
} from '@/components/domain/signing';
import { StatusBadge } from '@/components/domain/status';
import { EmptyState, ErrorState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import {
  InboxGroup,
  InboxItem,
  SplitInbox,
} from '@/components/layout/split-inbox';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Alert, Skeleton } from '@/components/ui/misc';
import { useMe } from '@/features/auth/api';
import { StepUpDialog } from '@/features/auth/mfa';
import { useMandates } from '@/features/controls/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import {
  useApprovalTypedData,
  useApproveRequest,
  useIdempotencyKey,
  useRequest,
  useRequests,
  useRequestTransition,
} from '@/features/requests/api';
import { ReasonDialog } from '@/features/requests/request-detail-page';
import {
  FlagList,
  PaymentOptions,
  RequestFacts,
  VendorHistory,
} from '@/features/requests/request-parts';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { Hex, RequestDetail } from '@/lib/api/types';
import { dueLabel } from '@/lib/format';
import { t } from '@/lib/i18n';
import { requestStatus } from '@/lib/status';
import { useWallet } from '@/lib/wallet/wallet-context';

/**
 * The signing step (F-038). The typed data is fetched only once every high
 * flag is acknowledged, shown in full, and passed to the wallet unchanged.
 */
function SignPanel({ request }: { request: RequestDetail }) {
  const scope = useOrgScope();
  const wallet = useWallet();
  const me = useMe();
  const mandates = useMandates(scope.orgId, request.treasuryId);
  const approve = useApproveRequest(scope.orgId, request.id);
  const transition = useRequestTransition(
    scope.orgId,
    request.id,
    request.version,
  );
  const [dialog, setDialog] = useState<'reject' | 'request-changes' | null>(
    null,
  );
  const idempotency = useIdempotencyKey();
  // A signed approval waiting for the second factor; it is sent unchanged afterwards.
  const [signed, setSigned] = useState<{
    signature: Hex;
    expiry: number;
    revision: number;
  } | null>(null);

  const send = async (approval: {
    signature: Hex;
    expiry: number;
    revision: number;
  }) => {
    await approve.mutateAsync({
      ...approval,
      idempotencyKey: idempotency.keyFor(approval.signature),
    });
    toast.success(t('Approved'), {
      description: t('The signature was verified and recorded.'),
    });
  };

  const blocked = request.approvalBlocked;
  const flagsOpen = request.highFlagsUnacked > 0;
  const typedData = useApprovalTypedData(
    scope.orgId,
    request.id,
    !blocked && !flagsOpen,
  );

  const approvers =
    mandates.data?.items.find((item) => item.status === 'Active')?.config
      .approvers ?? [];
  const linked =
    me.data?.wallets.map((item) => item.address.toLowerCase()) ?? [];
  const walletLinked =
    !wallet.address || linked.includes(wallet.address.toLowerCase());

  return (
    <Card>
      <CardHeader
        title={t('Decision')}
        description={t(
          'Approving is a wallet signature over the exact fields below. It is not a button in a database.',
        )}
      />
      <CardContent className="grid gap-4">
        {blocked ? (
          <Alert tone="warning" title={t('You cannot approve this request')}>
            <span className="inline-flex items-start gap-1.5">
              <Users className="mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
              {blocked.message}
            </span>
          </Alert>
        ) : (
          <>
            <div>
              <h3 className="mb-2 text-sm font-medium">
                {t('Payment option')}
              </h3>
              <PaymentOptions request={request} />
              <p className="mt-2 text-xs text-muted-foreground">
                {t('Your signature covers both options.')}
              </p>
            </div>

            <div>
              <h3 className="mb-2 text-sm font-medium">
                {t('Review what you sign')}
              </h3>
              {flagsOpen ? (
                <Alert tone="warning">
                  {t(
                    'Acknowledge every high-risk flag above. The data to sign is shown after that.',
                  )}
                </Alert>
              ) : typedData.isPending ? (
                <Skeleton className="h-64" />
              ) : typedData.isError ? (
                <ErrorState
                  error={typedData.error}
                  onRetry={() => void typedData.refetch()}
                />
              ) : (
                <TypedDataTable typedData={typedData.data} />
              )}
            </div>

            <WalletActionButton
              variant="primary"
              size="lg"
              chainId={typedData.data?.domain.chainId ?? 11155111}
              disabled={!typedData.data}
              blockedReason={
                flagsOpen
                  ? t(
                      'Signing is disabled until every high-risk flag is acknowledged.',
                    )
                  : !walletLinked
                    ? t(
                        'The connected wallet is not linked to your account. Link it under Wallets first.',
                      )
                    : undefined
              }
              requiredAddresses={
                approvers.length > 0
                  ? {
                      addresses: approvers,
                      message: t(
                        'The connected wallet is not in the mandate’s approver set.',
                      ),
                    }
                  : undefined
              }
              action={async () => {
                if (!typedData.data) return;
                // The revision the signed data was fetched for, kept for a retry after step-up.
                const approval = {
                  revision: request.revision,
                  signature: await wallet.signTypedData(typedData.data),
                  expiry: Number(typedData.data.message.expiry),
                };
                try {
                  await send(approval);
                } catch (error) {
                  if (!isApiError(error, 'STEP_UP_REQUIRED')) throw error;
                  setSigned(approval);
                }
              }}
            >
              <PenLine aria-hidden="true" />
              {t('Sign approval')}
            </WalletActionButton>
          </>
        )}

        <div className="flex flex-wrap gap-2 border-t pt-4">
          <Button onClick={() => setDialog('request-changes')}>
            {t('Request changes')}
          </Button>
          <Button variant="danger-outline" onClick={() => setDialog('reject')}>
            {t('Reject')}
          </Button>
        </div>
      </CardContent>

      <StepUpDialog
        open={signed !== null}
        onOpenChange={(open) => !open && setSigned(null)}
        onDone={() => {
          const approval = signed;
          setSigned(null);
          if (approval)
            send(approval).catch((error: unknown) =>
              toast.error(errorMessage(error)),
            );
        }}
      />

      <ReasonDialog
        open={dialog !== null}
        onOpenChange={(open) => !open && setDialog(null)}
        destructive={dialog === 'reject'}
        title={
          dialog === 'reject'
            ? t('Reject this request?')
            : t('Send back for changes?')
        }
        description={
          dialog === 'reject'
            ? t('A rejected request is closed and will not be paid.')
            : t(
                'The request returns to its creator as a draft, with your note.',
              )
        }
        confirmLabel={
          dialog === 'reject' ? t('Reject request') : t('Request changes')
        }
        pending={transition.isPending}
        onConfirm={(reason) =>
          dialog &&
          transition.mutate(
            { action: dialog, reason },
            {
              onSuccess: () => setDialog(null),
              onError: (error) => toast.error(errorMessage(error)),
            },
          )
        }
      />
    </Card>
  );
}

function ApprovalDetail({ id }: { id: string }) {
  const scope = useOrgScope();
  const query = useRequest(scope.orgId, id);

  if (query.isPending) {
    return (
      <Card className="p-4" aria-busy="true">
        <Skeleton className="h-6 w-1/2" />
        <Skeleton className="mt-6 h-72" />
      </Card>
    );
  }
  if (query.isError) {
    return (
      <Card>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </Card>
    );
  }
  const request = query.data;
  const awaiting = request.status === 'AwaitingApproval';

  return (
    <div className="grid gap-4">
      <Card>
        <CardContent>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-semibold">{request.vendorName}</h2>
              <p className="num text-sm text-muted-foreground">
                {request.invoiceNumber}
              </p>
            </div>
            <div className="text-right">
              <Amount value={request.amount} size="lg" />
              <div className="mt-1">
                <StatusBadge meta={requestStatus(request.status)} />
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {!awaiting && (
        <Alert
          tone={request.status === 'Approved' ? 'success' : 'neutral'}
          title={requestStatus(request.status).label}
          action={
            <Button asChild size="sm">
              <Link to={`${scope.base}/requests/${request.id}`}>
                {t('Open request')}
              </Link>
            </Button>
          }
        >
          {t('This request is no longer waiting for approval.')}
        </Alert>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <div className="grid gap-4">
          <Card>
            <CardHeader title={t('Fields')} />
            <CardContent>
              <RequestFacts request={request} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader title={t('Compared with this vendor’s history')} />
            <CardContent>
              <VendorHistory request={request} />
            </CardContent>
          </Card>
        </div>
        <div className="h-[30rem] xl:h-full xl:min-h-[30rem]">
          <DocumentViewer document={request.document} />
        </div>
      </div>

      <Card>
        <CardHeader
          title={t('Flags')}
          description={
            request.highFlagsUnacked > 0
              ? t(
                  '{{count}} high-risk flags must be acknowledged before you can sign.',
                  {
                    count: request.highFlagsUnacked,
                  },
                )
              : undefined
          }
        />
        <CardContent>
          <FlagList
            request={request}
            canAcknowledge={awaiting && !request.approvalBlocked}
          />
        </CardContent>
      </Card>

      {awaiting && <SignPanel key={request.version} request={request} />}
    </div>
  );
}

/** Approval inbox (WEB-009). */
export function ApprovalsPage() {
  const scope = useOrgScope();
  const { r: selectedId } = useParams();
  const query = useRequests(scope.orgId, 'AwaitingApproval');
  const listPath = `${scope.base}/approvals`;

  return (
    <Page
      width="wide"
      title={t('Approvals')}
      description={t(
        'Requests waiting for an approver’s signature. Review the flags, check the fields you sign, then sign with your wallet.',
      )}
    >
      <QueryBoundary query={query}>
        {({ items }) => {
          if (items.length === 0 && !selectedId) {
            return (
              <Card>
                <EmptyState
                  icon={ClipboardCheck}
                  title={t('Nothing to approve')}
                  description={t(
                    'When an operator submits a request, it appears here for an approver to review and sign.',
                  )}
                  action={
                    <Button asChild>
                      <Link to={`${scope.base}/requests`}>
                        {t('See all requests')}
                      </Link>
                    </Button>
                  }
                />
              </Card>
            );
          }
          return (
            <SplitInbox
              backTo={listPath}
              hasSelection={Boolean(selectedId)}
              listLabel={t('Requests awaiting approval')}
              list={
                <InboxGroup label={t('Awaiting approval')} count={items.length}>
                  {items.map((request) => {
                    const due = dueLabel(request.dueDate);
                    return (
                      <InboxItem
                        key={request.id}
                        to={`${listPath}/${request.id}`}
                        selected={request.id === selectedId}
                      >
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-base font-medium">
                            {request.vendorName}
                          </span>
                          <Amount
                            value={request.amount}
                            size="sm"
                            context="column"
                          />
                        </span>
                        <span className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span className="num">{request.invoiceNumber}</span>
                          <span
                            className={
                              due.soon ? 'text-warning-foreground' : ''
                            }
                          >
                            {due.text}
                          </span>
                        </span>
                        {request.openFlags > 0 && (
                          <span className="mt-1.5 flex">
                            <Badge
                              tone={
                                request.highFlagsUnacked > 0
                                  ? 'danger'
                                  : 'warning'
                              }
                            >
                              <Flag aria-hidden="true" />
                              {request.highFlagsUnacked > 0
                                ? t('{{count}} high-risk', {
                                    count: request.highFlagsUnacked,
                                  })
                                : t('{{count}} flags', {
                                    count: request.openFlags,
                                  })}
                            </Badge>
                          </span>
                        )}
                      </InboxItem>
                    );
                  })}
                </InboxGroup>
              }
              detail={
                selectedId ? (
                  <ApprovalDetail key={selectedId} id={selectedId} />
                ) : (
                  <Card>
                    <EmptyState
                      icon={ClipboardCheck}
                      title={t('Select a request')}
                      description={t(
                        'Choose a request to see its document, flags and the data you will sign.',
                      )}
                    />
                  </Card>
                )
              }
            />
          );
        }}
      </QueryBoundary>
    </Page>
  );
}
