import { formatUnits } from '@/lib/money';

import type { DemoRole, InvoiceStatus } from './types';

/** `1180000000` -> `1,180`; two decimals only when there is a fraction. */
export const fmt = (value: string | bigint, maxFraction = 2) =>
  formatUnits(value, 6, { minFraction: 0, maxFraction });

/** Two fixed decimals, for estimates such as 18.05 (rounded half up in integer math). */
export function fmt2(value: string | bigint) {
  const amount = BigInt(value);
  const rounded = (amount + 5_000n) / 10_000n;
  return formatUnits(rounded * 10_000n, 6, { minFraction: 2, maxFraction: 2 });
}

export const roleNames: Record<DemoRole, { name: string; title: string }> = {
  FINANCE: { name: 'Linh', title: 'Finance' },
  APPROVER: { name: 'An', title: 'Approver' },
  OWNER: { name: 'Minh', title: 'Owner' },
};

export const utc = (iso: string) =>
  `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;

export const utcSeconds = (iso: string) =>
  `${iso.slice(0, 10)} ${iso.slice(11, 19)} UTC`;

export const invoiceLabel: Record<InvoiceStatus, string> = {
  ABSENT: 'Not created',
  EXTRACTING: 'Extracting',
  DRAFT: 'Draft',
  AWAITING_APPROVAL: 'Awaiting approval',
  APPROVED: 'Approved',
  READY_WAITING_WINDOW: 'Approved',
  EXECUTING: 'Executing',
  PAYMENT_SUBMITTED: 'Payment submitted',
  OUTCOME_UNKNOWN: 'Outcome unknown',
  PAID: 'Paid',
};

export const invoiceTone = (status: InvoiceStatus) =>
  status === 'PAID'
    ? ('success' as const)
    : status === 'OUTCOME_UNKNOWN'
      ? ('warning' as const)
      : status === 'DRAFT' || status === 'EXTRACTING'
        ? ('neutral' as const)
        : ('info' as const);
