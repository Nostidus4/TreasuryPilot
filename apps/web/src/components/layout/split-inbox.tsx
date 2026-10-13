import { ArrowLeft } from 'lucide-react';
import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/**
 * Inbox layout: a list on the left, the selected item on the right.
 * Below `lg` only one pane shows: the list, or the item with a back link.
 */
export function SplitInbox({
  backTo,
  detail,
  hasSelection,
  list,
  listLabel,
}: {
  backTo: string;
  detail: ReactNode;
  hasSelection: boolean;
  list: ReactNode;
  listLabel: string;
}) {
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
      <aside
        aria-label={listLabel}
        className={cn(
          'overflow-hidden rounded-lg border bg-surface lg:sticky lg:top-[4.5rem] lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto',
          hasSelection && 'hidden lg:block',
        )}
      >
        {list}
      </aside>
      <section className={cn('min-w-0', !hasSelection && 'hidden lg:block')}>
        {hasSelection && (
          <Link
            to={backTo}
            className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground lg:hidden"
          >
            <ArrowLeft className="size-4" aria-hidden="true" />
            {t('Back to the list')}
          </Link>
        )}
        {detail}
      </section>
    </div>
  );
}

export function InboxGroup({
  children,
  count,
  label,
}: {
  children: ReactNode;
  count: number;
  label: string;
}) {
  return (
    <section aria-label={label}>
      <p className="flex items-center justify-between border-b bg-surface-muted px-3 py-1.5 text-xs font-medium text-muted-foreground">
        {label}
        <span className="num">{count}</span>
      </p>
      <ul className="divide-y border-b last:border-b-0">{children}</ul>
    </section>
  );
}

export function InboxItem({
  children,
  selected,
  to,
}: {
  children: ReactNode;
  selected: boolean;
  to: string;
}) {
  return (
    <li>
      <Link
        to={to}
        aria-current={selected ? 'true' : undefined}
        className={cn(
          'block border-l-2 px-3 py-2.5 hover:bg-surface-muted',
          selected ? 'border-primary bg-primary-muted' : 'border-transparent',
        )}
      >
        {children}
      </Link>
    </li>
  );
}
