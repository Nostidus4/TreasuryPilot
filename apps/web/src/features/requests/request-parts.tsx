import { Check, ShieldAlert, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';

import { Amount } from '@/components/domain/amount';
import { Address } from '@/components/domain/chain';
import { KeyValueList } from '@/components/domain/display';
import { StatusBadge } from '@/components/domain/status';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RadioCard, RadioGroup } from '@/components/ui/controls';
import { Field, Textarea } from '@/components/ui/input';
import { Alert } from '@/components/ui/misc';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useAcknowledgeFlag } from '@/features/requests/api';
import { errorMessage } from '@/lib/api/http';
import type { Flag, PaymentOption, RequestDetail } from '@/lib/api/types';
import { dueLabel, formatDate, formatDateTime } from '@/lib/format';
import { t } from '@/lib/i18n';
import { formatBps } from '@/lib/money';
import { requestStatus } from '@/lib/status';
import { cn } from '@/lib/utils';

export function RequestFacts({ request }: { request: RequestDetail }) {
  const due = dueLabel(request.dueDate);
  return (
    <KeyValueList
      items={[
        {
          label: t('Vendor'),
          value: <span className="font-medium">{request.vendorName}</span>,
        },
        {
          label: t('Invoice number'),
          value: <span className="num">{request.invoiceNumber}</span>,
        },
        { label: t('Amount'), value: <Amount value={request.amount} /> },
        {
          label: t('Due date'),
          hint: ['Paid', 'Rejected', 'Cancelled'].includes(request.status)
            ? undefined
            : due.text,
          value: formatDate(request.dueDate),
        },
        {
          label: t('Pay to'),
          value: request.payeeAddress ? (
            <Address address={request.payeeAddress} />
          ) : (
            '—'
          ),
        },
        ...(request.description
          ? [{ label: t('Description'), value: request.description }]
          : []),
        {
          label: t('Created'),
          value: `${request.createdBy.name} · ${formatDateTime(request.createdAt)}`,
        },
        {
          label: t('Revision'),
          value: <span className="num">{request.revision}</span>,
        },
      ]}
    />
  );
}

/** How this invoice compares with what this vendor was paid before (F-131). */
export function VendorHistory({ request }: { request: RequestDetail }) {
  const history = request.vendorHistory;
  if (history.paidCount === 0) {
    return (
      <Alert tone="warning" title={t('First payment to this vendor')}>
        {t('There is no history to compare this invoice with.')}
      </Alert>
    );
  }
  return (
    <div className="grid gap-3">
      <KeyValueList
        items={[
          {
            label: t('Paid invoices'),
            value: <span className="num">{history.paidCount}</span>,
          },
          {
            label: t('Average amount'),
            value: <Amount value={history.averageAmount} context="column" />,
          },
          {
            label: t('Last amount'),
            value: <Amount value={history.lastAmount} context="column" />,
          },
          {
            label: t('This invoice'),
            value: <Amount value={request.amount} context="column" />,
          },
          {
            label: t('Usual payee'),
            value: history.usualPayee ? (
              <Address address={history.usualPayee} />
            ) : (
              '—'
            ),
          },
          {
            label: t('Payee on this request'),
            value: (
              <span className="inline-flex flex-wrap items-center justify-end gap-1.5">
                {request.payeeAddress ? (
                  <Address address={request.payeeAddress} />
                ) : (
                  '—'
                )}
                {history.payeeChanged ? (
                  <Badge tone="danger">{t('Changed')}</Badge>
                ) : (
                  <Badge tone="success">{t('Same')}</Badge>
                )}
              </span>
            ),
          },
        ]}
      />
    </div>
  );
}

const severityTone = {
  HIGH: 'danger',
  MEDIUM: 'warning',
  LOW: 'neutral',
} as const;
const severityLabel = {
  HIGH: 'High risk',
  MEDIUM: 'Medium',
  LOW: 'Low',
} as const;

function FlagCard({
  canAcknowledge,
  flag,
  requestId,
}: {
  canAcknowledge: boolean;
  flag: Flag;
  requestId: string;
}) {
  const scope = useOrgScope();
  const acknowledge = useAcknowledgeFlag(scope.orgId, requestId);
  const [note, setNote] = useState('');
  const noteId = `ack-${flag.id}`;
  const duplicate = flag.duplicateOf;

  return (
    <li
      className={cn(
        'rounded-lg border',
        flag.acknowledged
          ? 'border-border'
          : flag.severity === 'HIGH'
            ? 'border-danger-border'
            : 'border-warning-border',
      )}
    >
      <div className="flex flex-wrap items-start gap-2 p-3">
        <ShieldAlert
          className={cn(
            'mt-0.5 size-4 shrink-0',
            flag.severity === 'HIGH' ? 'text-danger' : 'text-warning',
          )}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <p className="text-base font-medium">{flag.title}</p>
          <p className="num text-xs text-muted-foreground">{flag.code}</p>
          <p className="mt-1 text-sm text-muted-foreground">{flag.detail}</p>
        </div>
        <Badge tone={severityTone[flag.severity]}>
          {t(severityLabel[flag.severity])}
        </Badge>
      </div>

      {flag.evidence && (
        <dl className="divide-y border-t text-sm">
          {flag.evidence.map((item) => (
            <div
              key={item.label}
              className="grid gap-x-3 px-3 py-1.5 sm:grid-cols-[11rem_1fr]"
            >
              <dt className="text-muted-foreground">{item.label}</dt>
              <dd className="num break-all">{item.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {duplicate && (
        <div className="grid border-t sm:grid-cols-2 sm:divide-x">
          {[
            { heading: t('This request'), invoice: null },
            { heading: t('Earlier request'), invoice: duplicate },
          ].map(({ heading, invoice }) => (
            <div key={heading} className="p-3">
              <p className="text-xs font-medium text-muted-foreground">
                {heading}
              </p>
              {invoice ? (
                <div className="mt-1 grid gap-0.5 text-sm">
                  <Link
                    to={`${scope.base}/requests/${invoice.requestId}`}
                    className="num font-medium text-primary hover:underline"
                  >
                    {invoice.invoiceNumber}
                  </Link>
                  <span>{invoice.vendorName}</span>
                  <Amount value={invoice.amount} context="column" />
                  <span className="text-muted-foreground">
                    {t('Due {{date}}', { date: formatDate(invoice.dueDate) })}
                  </span>
                  <StatusBadge
                    meta={requestStatus(invoice.status)}
                    className="w-fit"
                  />
                </div>
              ) : (
                <p className="mt-1 text-sm text-muted-foreground">
                  {t(
                    'Same vendor and amount. Compare the invoice numbers and documents before deciding.',
                  )}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="border-t bg-surface-muted p-3">
        {flag.acknowledged ? (
          <p className="flex items-start gap-1.5 text-sm">
            <Check
              className="mt-0.5 size-3.5 shrink-0 text-success"
              aria-hidden="true"
            />
            <span>
              {t('Acknowledged by {{name}}', { name: flag.acknowledged.by })} ·{' '}
              {formatDateTime(flag.acknowledged.at)}
              {flag.acknowledged.note && (
                <span className="block text-muted-foreground">
                  “{flag.acknowledged.note}”
                </span>
              )}
            </span>
          </p>
        ) : canAcknowledge ? (
          <form
            className="grid gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              acknowledge.mutate({ flagId: flag.id, note });
            }}
          >
            <Field
              htmlFor={noteId}
              label={t('Why is it acceptable to proceed?')}
              optional={flag.severity !== 'HIGH'}
              error={
                acknowledge.isError
                  ? errorMessage(acknowledge.error)
                  : undefined
              }
            >
              <Textarea
                id={noteId}
                className="min-h-16 bg-surface"
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder={t(
                  'e.g. Confirmed the new address with the vendor by phone',
                )}
              />
            </Field>
            <Button
              type="submit"
              size="sm"
              className="justify-self-start"
              loading={acknowledge.isPending}
              disabled={flag.severity === 'HIGH' && !note.trim()}
            >
              {t('Acknowledge flag')}
            </Button>
          </form>
        ) : (
          <p className="text-sm text-muted-foreground">
            {t(
              'Not acknowledged. An approver must acknowledge it before signing.',
            )}
          </p>
        )}
      </div>
    </li>
  );
}

/** Flags with evidence. High flags need a written acknowledgement (FR-316). */
export function FlagList({
  canAcknowledge,
  request,
}: {
  canAcknowledge: boolean;
  request: RequestDetail;
}) {
  if (request.flags.length === 0) {
    return (
      <p className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Check className="size-4 text-success" aria-hidden="true" />
        {t('No flags were raised for this request.')}
      </p>
    );
  }
  return (
    <ul className="grid gap-3">
      {request.flags.map((flag) => (
        <FlagCard
          key={flag.id}
          flag={flag}
          requestId={request.id}
          canAcknowledge={canAcknowledge}
        />
      ))}
    </ul>
  );
}

/**
 * Early vs standard payment (ADR-019). One signature covers both amounts;
 * the choice here records the approver's preference.
 */
export function PaymentOptions({
  onChange,
  request,
  value,
}: {
  onChange?: (value: PaymentOption['kind']) => void;
  request: RequestDetail;
  value?: PaymentOption['kind'];
}) {
  const hasEarly = request.options.some((option) => option.kind === 'EARLY');
  const body = (option: PaymentOption) => (
    <>
      <span className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-base font-medium">
          {option.kind === 'EARLY' ? t('Pay early') : t('Pay on the due date')}
        </span>
        <Amount value={option.amount} context="column" />
      </span>
      <span className="mt-0.5 block text-sm text-muted-foreground">
        {t('Pay by {{date}}', { date: formatDate(option.payBy) })}
        {option.kind === 'EARLY' && request.terms.earlyDiscountBps && (
          <>
            {' · '}
            {t('{{rate}} discount', {
              rate: formatBps(request.terms.earlyDiscountBps),
            })}
            {' · '}
            {t('saves')}{' '}
            <Amount value={option.saving} size="sm" context="column" />
          </>
        )}
      </span>
    </>
  );

  if (!onChange) {
    return (
      <ul className="grid gap-2">
        {request.options.map((option) => (
          <li key={option.kind} className="rounded-lg border p-3">
            {body(option)}
          </li>
        ))}
      </ul>
    );
  }
  return (
    <div className="grid gap-2">
      <RadioGroup
        value={value}
        onValueChange={(next) => onChange(next as PaymentOption['kind'])}
        aria-label={t('Payment option')}
      >
        {request.options.map((option) => (
          <RadioCard key={option.kind} value={option.kind}>
            {body(option)}
          </RadioCard>
        ))}
      </RadioGroup>
      {hasEarly && (
        <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
          <TriangleAlert
            className="mt-0.5 size-3 shrink-0"
            aria-hidden="true"
          />
          {t(
            'Your signature authorizes both amounts. The contract pays the early amount only if the payment lands before the early deadline; otherwise it pays the standard amount.',
          )}
        </p>
      )}
    </div>
  );
}

export function RequestTimeline({ request }: { request: RequestDetail }) {
  return (
    <ol className="grid gap-3">
      {request.timeline.map((entry, index) => (
        <li key={`${entry.at}-${index}`} className="flex gap-3">
          <span
            className="mt-1.5 size-2 shrink-0 rounded-full bg-border-strong"
            aria-hidden="true"
          />
          <span>
            <span className="block text-base">{entry.label}</span>
            <span className="text-xs text-subtle-foreground">
              {formatDateTime(entry.at)}
            </span>
          </span>
        </li>
      ))}
    </ol>
  );
}
