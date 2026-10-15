import { TriangleAlert } from 'lucide-react';
import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';

import { Amount } from '@/components/domain/amount';
import { KeyValueList, UsageBar } from '@/components/domain/display';
import { AiExplanation } from '@/components/domain/status';
import { EmptyState, QueryBoundary } from '@/components/feedback';
import { Page } from '@/components/layout/page';
import {
  InboxGroup,
  InboxItem,
  SplitInbox,
} from '@/components/layout/split-inbox';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader } from '@/components/ui/card';
import { Select } from '@/components/ui/controls';
import { Field, Textarea } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import {
  useException,
  useGrantExceptionTx,
  useRejectException,
  useReviewAction,
  useReviewItems,
} from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import { errorMessage, isApiError } from '@/lib/api/http';
import type { ReviewItem } from '@/lib/api/types';
import { formatDateTime, formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { roleLabels } from '@/lib/status';

const typeLabel: Record<ReviewItem['type'], string> = {
  EXCEPTION: 'Exception request',
  UNKNOWN_OPERATION: 'Unknown outcome',
  FAILED_STEP: 'Failed step',
  VERIFICATION_MISMATCH: 'Verification mismatch',
  FEE_ACCEPTANCE: 'Fee acceptance',
};

const actionLabel: Record<ReviewItem['actions'][number], string> = {
  RETRY: 'Look up the transaction again',
  CANCEL: 'Cancel the operation',
  RESOLVE: 'Mark resolved',
  EDIT_REAPPROVE: 'Edit and re-approve',
};

/** Shown when the item changed under the user: acting again needs fresh data. */
function StalePrompt({ orgId }: { orgId: string }) {
  const queryClient = useQueryClient();
  return (
    <Alert
      tone="warning"
      title={t('This item changed')}
      action={
        <Button
          size="sm"
          variant="primary"
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: ['org', orgId] });
          }}
        >
          {t('Refresh')}
        </Button>
      }
    >
      {t('Someone else may have handled it. Refresh to see the latest state.')}
    </Alert>
  );
}

/**
 * One-time exception (F-025). Granting is a governance transaction (M16-D3):
 * the numbers come from the engine; the AI draft is only a labelled summary.
 */
function ExceptionPanel({ item }: { item: ReviewItem }) {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const query = useException(scope.orgId, item.requestId);
  const grant = useGrantExceptionTx(scope.orgId);
  const reject = useRejectException(scope.orgId);
  const [expiryHours, setExpiryHours] = useState('24');
  const [reason, setReason] = useState('');
  const isOwner = scope.can('OWN');

  return (
    <QueryBoundary query={query}>
      {({ aiDraft, exception, numbers }) => (
        <div className="grid gap-4">
          <Card>
            <CardHeader
              title={t('The numbers')}
              description={t(
                'From the policy engine for the current snapshot.',
              )}
            />
            <CardContent className="grid gap-4">
              <KeyValueList
                items={[
                  {
                    label: t('Requested'),
                    value: <Amount value={numbers.requested} />,
                  },
                  {
                    label: t('Per-request limit'),
                    value: (
                      <Amount value={numbers.perRequestCap} context="column" />
                    ),
                  },
                  {
                    label: (
                      <span className="font-medium text-foreground">
                        {t('Over the limit by')}
                      </span>
                    ),
                    value: <Amount value={numbers.overBy} context="column" />,
                  },
                ]}
              />
              <UsageBar
                label={t('Today’s payments if this is paid')}
                used={(
                  BigInt(numbers.dailyUsed) + BigInt(numbers.requested)
                ).toString()}
                limit={numbers.dailyLimit}
              />
            </CardContent>
          </Card>

          {aiDraft && (
            <AiExplanation title={t('AI summary of the request')}>
              {aiDraft}
            </AiExplanation>
          )}

          {exception.status === 'GovernancePending' &&
            exception.governanceTxId && (
              <Alert
                tone="info"
                title={t('Waiting for owner signatures')}
                action={
                  <Button asChild size="sm" variant="primary">
                    <Link
                      to={`${scope.base}/governance/${exception.governanceTxId}`}
                    >
                      {t('Open transaction')}
                    </Link>
                  </Button>
                }
              >
                {t(
                  'The exception takes effect only when the governance transaction executes.',
                )}
              </Alert>
            )}
          {exception.status === 'Granted' && (
            <Alert tone="success" title={t('Exception granted on-chain')} />
          )}
          {exception.status === 'Rejected' && (
            <Alert tone="neutral" title={t('Exception rejected')} />
          )}

          {exception.status === 'Open' &&
            (isOwner ? (
              <Card>
                <CardHeader
                  title={t('Decision')}
                  description={t(
                    'An exception covers this one request and expires on its own.',
                  )}
                />
                <CardContent className="grid gap-4">
                  <Field
                    htmlFor="exception-expiry"
                    label={t('Exception valid for')}
                  >
                    <Select
                      id="exception-expiry"
                      className="sm:w-56"
                      value={expiryHours}
                      onValueChange={setExpiryHours}
                      options={[
                        { value: '6', label: t('6 hours') },
                        { value: '24', label: t('24 hours') },
                        { value: '72', label: t('3 days') },
                      ]}
                    />
                  </Field>
                  {isApiError(grant.error, 'STALE_ITEM') ? (
                    <StalePrompt orgId={scope.orgId} />
                  ) : (
                    grant.isError && (
                      <Alert tone="danger">{errorMessage(grant.error)}</Alert>
                    )
                  )}
                  <Button
                    variant="primary"
                    className="justify-self-start"
                    loading={grant.isPending}
                    onClick={() =>
                      grant.mutate(
                        {
                          requestId: exception.requestId,
                          expiryHours: Number(expiryHours),
                        },
                        {
                          onSuccess: ({ governanceTx }) =>
                            navigate(
                              `${scope.base}/governance/${governanceTx.id}`,
                            ),
                        },
                      )
                    }
                  >
                    {t('Create governance transaction to grant')}
                  </Button>
                  <form
                    className="grid gap-3 border-t pt-4"
                    onSubmit={(event) => {
                      event.preventDefault();
                      reject.mutate(
                        { requestId: exception.requestId, reason },
                        {
                          onSuccess: () =>
                            toast.success(t('Exception rejected')),
                          onError: (error) => toast.error(errorMessage(error)),
                        },
                      );
                    }}
                  >
                    <Field
                      htmlFor="exception-reject"
                      label={t('Or reject, with a reason')}
                    >
                      <Textarea
                        id="exception-reject"
                        value={reason}
                        onChange={(event) => setReason(event.target.value)}
                      />
                    </Field>
                    <Button
                      type="submit"
                      variant="danger-outline"
                      className="justify-self-start"
                      loading={reject.isPending}
                      disabled={!reason.trim()}
                    >
                      {t('Reject exception')}
                    </Button>
                  </form>
                </CardContent>
              </Card>
            ) : (
              <Alert tone="neutral" title={t('Waiting for an Owner')}>
                {t('Only Safe owners can grant or reject an exception.')}
              </Alert>
            ))}
        </div>
      )}
    </QueryBoundary>
  );
}

function ActionPanel({ item }: { item: ReviewItem }) {
  const scope = useOrgScope();
  const act = useReviewAction(scope.orgId);
  const [action, setAction] = useState<string>(item.actions[0] ?? 'RESOLVE');
  const [note, setNote] = useState('');
  const allowed = scope.can(...item.roles);
  const stale = isApiError(act.error, 'STALE_ITEM');

  if (!allowed) {
    return (
      <Alert tone="neutral" title={t('Another role handles this')}>
        {t('This item is routed to: {{roles}}.', {
          roles: item.roles.map((role) => t(roleLabels[role])).join(', '),
        })}
      </Alert>
    );
  }
  return (
    <Card>
      <CardHeader
        title={t('Action')}
        description={t(
          'Every action is recorded with your note in the audit log.',
        )}
      />
      <CardContent>
        <form
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            act.mutate(
              { id: item.id, action, note, version: item.version },
              {
                onSuccess: () => {
                  toast.success(
                    action === 'RETRY'
                      ? t('Looking up the transaction…')
                      : t('Recorded'),
                  );
                  setNote('');
                },
              },
            );
          }}
        >
          <Field htmlFor="review-action" label={t('What do you want to do?')}>
            <Select
              id="review-action"
              value={action}
              onValueChange={setAction}
              options={item.actions.map((value) => ({
                value,
                label: t(actionLabel[value]),
              }))}
            />
          </Field>
          {stale && <StalePrompt orgId={scope.orgId} />}
          <Field
            htmlFor="review-note"
            label={t('Note')}
            error={act.isError && !stale ? errorMessage(act.error) : undefined}
          >
            <Textarea
              id="review-note"
              value={note}
              aria-invalid={act.isError}
              onChange={(event) => setNote(event.target.value)}
            />
          </Field>
          <Button
            type="submit"
            variant="primary"
            className="justify-self-start"
            loading={act.isPending}
            disabled={!note.trim()}
          >
            {t('Confirm')}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ItemDetail({ item }: { item: ReviewItem }) {
  const scope = useOrgScope();
  return (
    <div className="grid gap-4">
      <Card>
        <CardContent>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h2 className="text-xl font-semibold">{item.title}</h2>
            <Badge tone={item.status === 'Open' ? 'warning' : 'success'}>
              {item.status === 'Open' ? t('Open') : t('Resolved')}
            </Badge>
          </div>
          <p className="mt-2 text-base text-muted-foreground">{item.detail}</p>
          <p className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
            <span>{t(typeLabel[item.type])}</span>
            <span>{formatDateTime(item.createdAt)}</span>
            {item.requestId && (
              <Link
                className="text-primary hover:underline"
                to={`${scope.base}/requests/${item.requestId}`}
              >
                {t('Open request')}
              </Link>
            )}
            {item.planId && (
              <Link
                className="text-primary hover:underline"
                to={`${scope.tBase}/plans/${item.planId}`}
              >
                {t('Open plan')}
              </Link>
            )}
          </p>
        </CardContent>
      </Card>

      {item.type === 'UNKNOWN_OPERATION' && item.status === 'Open' && (
        <Alert
          tone="warning"
          title={t('Checking the chain — no new payment will be sent')}
        >
          {t(
            'Unknown is not failed. The transaction may still be mined. Do not pay this again by hand until its outcome is known.',
          )}
        </Alert>
      )}

      {item.resolution && (
        <Alert tone="success" title={t('Resolved')}>
          {item.resolution.note} · {formatDateTime(item.resolution.at)}
        </Alert>
      )}

      {item.type === 'EXCEPTION' ? (
        <ExceptionPanel item={item} />
      ) : (
        item.status === 'Open' && <ActionPanel key={item.id} item={item} />
      )}
    </div>
  );
}

/** Review and exception console (WEB-013). */
export function ReviewPage() {
  const scope = useOrgScope();
  const [params] = useSearchParams();
  const selectedId = params.get('item');
  const query = useReviewItems(scope.orgId);
  const listPath = `${scope.base}/review`;

  return (
    <Page
      width="wide"
      title={t('Review')}
      description={t(
        'Things the agent will not decide on its own: payments over a limit, transactions with an unknown outcome, and results that do not match the plan.',
      )}
    >
      <QueryBoundary query={query}>
        {({ items }) => {
          if (items.length === 0) {
            return (
              <Card>
                <EmptyState
                  icon={TriangleAlert}
                  title={t('Nothing needs review')}
                  description={t(
                    'Exceptions, unknown outcomes and mismatches appear here when they happen. Plans that pass policy run without stopping here.',
                  )}
                />
              </Card>
            );
          }
          const open = items.filter((item) => item.status === 'Open');
          const resolved = items.filter((item) => item.status === 'Resolved');
          const selected = items.find((item) => item.id === selectedId);
          const row = (item: ReviewItem) => (
            <InboxItem
              key={item.id}
              to={`${listPath}?item=${item.id}`}
              selected={item.id === selectedId}
            >
              <p className="text-base font-medium">{item.title}</p>
              <p className="mt-0.5 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                <span>{t(typeLabel[item.type])}</span>
                <span>{formatRelative(item.createdAt)}</span>
              </p>
            </InboxItem>
          );
          return (
            <SplitInbox
              backTo={listPath}
              hasSelection={Boolean(selected)}
              listLabel={t('Review items')}
              list={
                <>
                  {open.length > 0 && (
                    <InboxGroup label={t('Open')} count={open.length}>
                      {open.map(row)}
                    </InboxGroup>
                  )}
                  {resolved.length > 0 && (
                    <InboxGroup label={t('Resolved')} count={resolved.length}>
                      {resolved.map(row)}
                    </InboxGroup>
                  )}
                </>
              }
              detail={
                selected ? (
                  <ItemDetail key={selected.id} item={selected} />
                ) : (
                  <Card>
                    <EmptyState
                      icon={TriangleAlert}
                      title={t('Select an item')}
                      description={t(
                        'Choose an item to see what happened and what you can do about it.',
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
