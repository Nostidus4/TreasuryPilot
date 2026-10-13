import { zodResolver } from '@hookform/resolvers/zod';
import { Sparkles, UserPen } from 'lucide-react';
import type { ReactNode } from 'react';
import { Controller, useForm } from 'react-hook-form';
import { z } from 'zod';

import { AmountInput } from '@/components/domain/amount';
import { Select, Switch } from '@/components/ui/controls';
import { Field, Input, Label, Textarea } from '@/components/ui/input';
import { useAssetInfo } from '@/lib/api/chains';
import type { ExtractedField, Vendor } from '@/lib/api/types';
import { t } from '@/lib/i18n';
import { formatUnits, parseUnits } from '@/lib/money';
import { cn } from '@/lib/utils';

export interface RequestFormValues {
  vendorId: string;
  invoiceNumber: string;
  amount: string;
  dueDate: string;
  description: string;
  earlyEnabled: boolean;
  earlyPayDate: string;
  earlyDiscountPercent: string;
}

/** What the API needs, with the amount in base units and ISO dates. */
export interface RequestFormResult {
  vendorId: string;
  invoiceNumber: string;
  amount: string;
  dueDate: string;
  description: string;
  earlyPayDate?: string;
  earlyDiscountBps?: number;
}

const endOfDayUtc = (date: string) => `${date}T23:59:59.000Z`;
const toDateInput = (iso?: string) => (iso ? iso.slice(0, 10) : '');

function schema(decimals: number) {
  return z
    .object({
      vendorId: z.string().min(1, t('Choose a vendor.')),
      invoiceNumber: z.string().trim().min(1, t('Enter the invoice number.')),
      amount: z.string().superRefine((value, context) => {
        const parsed = parseUnits(value, decimals);
        if (parsed.ok && parsed.value > 0n) return;
        const messages = {
          EMPTY: t('Enter an amount.'),
          NOT_A_NUMBER: t(
            'Use digits and a decimal point, for example 1450.00.',
          ),
          NEGATIVE: t('The amount must be greater than zero.'),
          TOO_PRECISE: t('This asset has {{count}} decimal places at most.', {
            count: decimals,
          }),
        };
        context.addIssue({
          code: z.ZodIssueCode.custom,
          message: parsed.ok
            ? t('The amount must be greater than zero.')
            : messages[parsed.error],
        });
      }),
      dueDate: z.string().min(1, t('Choose the due date.')),
      description: z.string(),
      earlyEnabled: z.boolean(),
      earlyPayDate: z.string(),
      earlyDiscountPercent: z.string(),
    })
    .superRefine((values, context) => {
      if (!values.earlyEnabled) return;
      if (!values.earlyPayDate) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['earlyPayDate'],
          message: t('Choose the early-payment deadline.'),
        });
      } else if (values.dueDate && values.earlyPayDate >= values.dueDate) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['earlyPayDate'],
          message: t('The early deadline must be before the due date.'),
        });
      }
      const percent = Number(values.earlyDiscountPercent);
      if (
        !/^\d+(\.\d{1,2})?$/.test(values.earlyDiscountPercent) ||
        percent <= 0 ||
        percent > 20
      ) {
        context.addIssue({
          code: z.ZodIssueCode.custom,
          path: ['earlyDiscountPercent'],
          message: t('Enter a discount between 0.01% and 20%.'),
        });
      }
    });
}

/** Marks where a value came from: read by AI (with confidence) or typed. */
function Provenance({
  changed,
  field,
}: {
  changed: boolean;
  field?: ExtractedField;
}) {
  if (!field) return null;
  if (changed || field.source === 'USER') {
    return (
      <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
        <UserPen className="size-3" aria-hidden="true" />
        {t('Edited by you')}
      </span>
    );
  }
  const confidence = field.confidence ?? 1;
  const low = confidence < 0.8;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 text-xs',
        low ? 'font-medium text-warning-foreground' : 'text-ai-foreground',
      )}
    >
      <Sparkles className="size-3" aria-hidden="true" />
      {t('Read by AI · {{percent}}% confidence', {
        percent: Math.round(confidence * 100),
      })}
      {low && ` — ${t('check against the document')}`}
    </span>
  );
}

export function RequestForm({
  children,
  defaults,
  extracted,
  formId,
  onSubmit,
  serverErrors,
  vendorLocked,
  vendors,
}: {
  /** Buttons, rendered inside the form after the fields. */
  children: ReactNode;
  defaults?: Partial<RequestFormValues>;
  /** Extraction output, keyed by field, for provenance markers. */
  extracted?: ExtractedField[];
  formId?: string;
  onSubmit: (result: RequestFormResult) => void;
  serverErrors?: Record<string, string>;
  vendorLocked?: boolean;
  vendors: Vendor[];
}) {
  const info = useAssetInfo();
  const decimals = info?.asset.decimals ?? 6;
  const initial: RequestFormValues = {
    vendorId: '',
    invoiceNumber: '',
    amount: '',
    dueDate: '',
    description: '',
    earlyEnabled: false,
    earlyPayDate: '',
    earlyDiscountPercent: '',
    ...defaults,
  };
  const form = useForm<RequestFormValues>({
    resolver: zodResolver(schema(decimals)),
    defaultValues: initial,
  });
  const { errors, dirtyFields } = form.formState;
  const earlyEnabled = form.watch('earlyEnabled');
  const byKey = (key: string) => extracted?.find((field) => field.key === key);
  const error = (name: keyof RequestFormValues) =>
    errors[name]?.message ?? serverErrors?.[name];

  const submit = form.handleSubmit((values) => {
    const amount = parseUnits(values.amount, decimals);
    if (!amount.ok) return;
    onSubmit({
      vendorId: values.vendorId,
      invoiceNumber: values.invoiceNumber.trim(),
      amount: amount.value.toString(),
      dueDate: endOfDayUtc(values.dueDate),
      description: values.description.trim(),
      ...(values.earlyEnabled
        ? {
            earlyPayDate: endOfDayUtc(values.earlyPayDate),
            earlyDiscountBps: Math.round(
              Number(values.earlyDiscountPercent) * 100,
            ),
          }
        : {}),
    });
  });

  return (
    <form
      id={formId}
      noValidate
      className="grid gap-4"
      onSubmit={(event) => void submit(event)}
    >
      <Field
        htmlFor="vendorId"
        label={t('Vendor')}
        error={error('vendorId')}
        hint={
          <Provenance
            field={byKey('vendor')}
            changed={Boolean(dirtyFields.vendorId)}
          />
        }
      >
        <Controller
          control={form.control}
          name="vendorId"
          render={({ field }) => (
            <Select
              id="vendorId"
              value={field.value || undefined}
              onValueChange={field.onChange}
              disabled={vendorLocked}
              invalid={Boolean(error('vendorId'))}
              placeholder={t('Choose a vendor')}
              options={vendors.map((vendor) => ({
                value: vendor.id,
                label: vendor.payeeAddress
                  ? vendor.name
                  : `${vendor.name} — ${t('no registered payee')}`,
                disabled: !vendor.payeeAddress,
              }))}
            />
          )}
        />
      </Field>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field
          htmlFor="invoiceNumber"
          label={t('Invoice number')}
          error={error('invoiceNumber')}
          hint={
            <Provenance
              field={byKey('invoiceNumber')}
              changed={Boolean(dirtyFields.invoiceNumber)}
            />
          }
        >
          <Input
            id="invoiceNumber"
            className="num"
            aria-invalid={Boolean(error('invoiceNumber'))}
            {...form.register('invoiceNumber')}
          />
        </Field>
        <Field
          htmlFor="dueDate"
          label={t('Due date')}
          error={error('dueDate')}
          hint={
            <Provenance
              field={byKey('dueDate')}
              changed={Boolean(dirtyFields.dueDate)}
            />
          }
        >
          <Input
            id="dueDate"
            type="date"
            aria-invalid={Boolean(error('dueDate'))}
            {...form.register('dueDate')}
          />
        </Field>
      </div>

      <Field
        htmlFor="amount"
        label={t('Amount')}
        error={error('amount')}
        hint={
          <Provenance
            field={byKey('amount')}
            changed={Boolean(dirtyFields.amount)}
          />
        }
      >
        <AmountInput
          id="amount"
          aria-invalid={Boolean(error('amount'))}
          {...form.register('amount')}
        />
      </Field>

      <Field htmlFor="description" label={t('Description')} optional>
        <Textarea id="description" {...form.register('description')} />
      </Field>

      <fieldset className="rounded-lg border p-3">
        <legend className="sr-only">{t('Payment terms')}</legend>
        <div className="flex items-start justify-between gap-3">
          <div>
            <Label htmlFor="earlyEnabled">{t('Early-payment discount')}</Label>
            <p className="text-sm text-muted-foreground">
              {t(
                'If the invoice offers a discount for paying early, the plan can use it when the treasury has room.',
              )}
            </p>
          </div>
          <Controller
            control={form.control}
            name="earlyEnabled"
            render={({ field }) => (
              <Switch
                id="earlyEnabled"
                checked={field.value}
                onCheckedChange={field.onChange}
              />
            )}
          />
        </div>
        {earlyEnabled && (
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            <Field
              htmlFor="earlyPayDate"
              label={t('Pay by')}
              error={error('earlyPayDate')}
            >
              <Input
                id="earlyPayDate"
                type="date"
                aria-invalid={Boolean(error('earlyPayDate'))}
                {...form.register('earlyPayDate')}
              />
            </Field>
            <Field
              htmlFor="earlyDiscountPercent"
              label={t('Discount (%)')}
              error={error('earlyDiscountPercent')}
            >
              <Input
                id="earlyDiscountPercent"
                inputMode="decimal"
                className="num"
                placeholder="2.00"
                aria-invalid={Boolean(error('earlyDiscountPercent'))}
                {...form.register('earlyDiscountPercent')}
              />
            </Field>
          </div>
        )}
      </fieldset>

      {children}
    </form>
  );
}

/** Form defaults from a stored request. */
// eslint-disable-next-line react-refresh/only-export-components
export function formDefaults(
  request: {
    vendorId: string;
    invoiceNumber: string;
    amount: string;
    dueDate: string;
    description: string;
    terms: { earlyPayDate?: string; earlyDiscountBps?: number };
  },
  decimals: number,
): RequestFormValues {
  const { earlyDiscountBps, earlyPayDate } = request.terms;
  return {
    vendorId: request.vendorId,
    invoiceNumber: request.invoiceNumber,
    amount: formatUnits(request.amount, decimals, { group: false }),
    dueDate: toDateInput(request.dueDate),
    description: request.description,
    earlyEnabled: Boolean(earlyDiscountBps),
    earlyPayDate: toDateInput(earlyPayDate),
    earlyDiscountPercent: earlyDiscountBps
      ? (earlyDiscountBps / 100).toFixed(2)
      : '',
  };
}
