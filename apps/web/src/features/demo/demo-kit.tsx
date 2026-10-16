import { CheckCircle2, Circle, CircleHelp, Loader2 } from 'lucide-react';
import type { ReactNode } from 'react';

import { Badge, type Tone } from '@/components/ui/badge';
import { cn } from '@/lib/utils';

import { usd, type StepState } from './scenario';

export function Money({
  value,
  className,
  sign,
}: {
  value: bigint;
  className?: string;
  sign?: '+' | '-';
}) {
  return (
    <span className={cn('num whitespace-nowrap font-medium', className)}>
      {sign}
      {usd(value)} <span className="text-xs text-muted-foreground">USDC</span>
    </span>
  );
}

/** `2026-10-16T10:05:00Z` → `Oct 16, 10:05:00 UTC` (scenario UTC, no locale). */
export function utc(iso: string, withSeconds = true) {
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  const month = months[Number(iso.slice(5, 7)) - 1];
  const time = iso.slice(11, withSeconds ? 19 : 16);
  return `${month} ${Number(iso.slice(8, 10))}, ${time} UTC`;
}

export function SimBadge({ children = 'Simulated' }: { children?: ReactNode }) {
  return <Badge tone="warning">{children}</Badge>;
}

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <Badge tone={tone}>{children}</Badge>;
}

const stepTone: Record<StepState, Tone> = {
  Planned: 'neutral',
  Submitted: 'info',
  Confirmed: 'success',
  'Outcome unknown': 'warning',
};

export function StepBadge({ state }: { state: StepState }) {
  const Icon =
    state === 'Confirmed'
      ? CheckCircle2
      : state === 'Submitted'
        ? Loader2
        : state === 'Outcome unknown'
          ? CircleHelp
          : Circle;
  return (
    <Badge tone={stepTone[state]}>
      <Icon
        className={cn(state === 'Submitted' && 'animate-spin')}
        aria-hidden="true"
      />
      {state}
    </Badge>
  );
}

export function Check({
  ok = true,
  children,
}: {
  ok?: boolean;
  children: ReactNode;
}) {
  return (
    <li className="flex items-start gap-2 text-sm">
      {ok ? (
        <CheckCircle2
          className="mt-0.5 size-4 shrink-0 text-success"
          aria-hidden="true"
        />
      ) : (
        <Circle
          className="mt-0.5 size-4 shrink-0 text-subtle-foreground"
          aria-hidden="true"
        />
      )}
      <span className={cn(!ok && 'text-muted-foreground')}>{children}</span>
    </li>
  );
}

/** One line of an arithmetic breakdown: label on the left, amount on the right. */
export function Row({
  label,
  value,
  sign,
  strong,
  hint,
  className,
}: {
  label: ReactNode;
  value: bigint;
  sign?: '+' | '-';
  strong?: boolean;
  hint?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex items-baseline justify-between gap-4 py-1.5',
        strong && 'border-t pt-2 font-semibold',
        className,
      )}
    >
      <span className="text-muted-foreground">
        <span className={cn(strong && 'text-foreground')}>{label}</span>
        {hint && (
          <span className="block text-xs text-subtle-foreground">{hint}</span>
        )}
      </span>
      <Money value={value} sign={sign} />
    </div>
  );
}

export function Ref({ children }: { children: ReactNode }) {
  return (
    <code className="rounded-sm border bg-surface-muted px-1 py-0.5 font-mono text-xs">
      {children}
    </code>
  );
}

const STATUS_LABEL: Record<string, string> = {
  EXTRACTING: 'Extracting',
  DRAFT: 'Draft',
  AWAITING_APPROVAL: 'Awaiting approval',
  APPROVED: 'Approved',
  READY_WAITING_WINDOW: 'Ready - waiting for approved window',
  EXECUTING: 'Executing',
  PAYMENT_SUBMITTED: 'Payment submitted',
  OUTCOME_UNKNOWN: 'Outcome unknown',
  PAID: 'Paid',
};
export const statusLabel = (status: string) => STATUS_LABEL[status] ?? status;
