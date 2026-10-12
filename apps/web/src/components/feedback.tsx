import type { UseQueryResult } from '@tanstack/react-query';
import { CircleAlert, RotateCw, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/misc';
import { errorMessage, isApiError } from '@/lib/api/http';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';

/** An empty state always says what to do next. */
export function EmptyState({
  action,
  className,
  description,
  icon: Icon,
  title,
}: {
  action?: ReactNode;
  className?: string;
  description: ReactNode;
  icon?: LucideIcon;
  title: string;
}) {
  return (
    <div
      className={cn(
        'grid place-items-center px-6 py-12 text-center',
        className,
      )}
    >
      <div className="max-w-sm">
        {Icon && (
          <span className="mx-auto grid size-10 place-items-center rounded-lg border bg-surface-muted text-muted-foreground">
            <Icon className="size-5" aria-hidden="true" />
          </span>
        )}
        <h3 className="mt-3 text-lg font-semibold">{title}</h3>
        <p className="mt-1 text-base text-muted-foreground">{description}</p>
        {action && (
          <div className="mt-4 flex justify-center gap-2">{action}</div>
        )}
      </div>
    </div>
  );
}

export function ErrorState({
  className,
  error,
  onRetry,
  title,
}: {
  className?: string;
  error: unknown;
  onRetry?: () => void;
  title?: string;
}) {
  const notFound = isApiError(error) && error.status === 404;
  return (
    <div
      role="alert"
      className={cn(
        'grid place-items-center px-6 py-12 text-center',
        className,
      )}
    >
      <div className="max-w-sm">
        <span className="mx-auto grid size-10 place-items-center rounded-lg border border-danger-border bg-danger-muted text-danger-foreground">
          <CircleAlert className="size-5" aria-hidden="true" />
        </span>
        <h3 className="mt-3 text-lg font-semibold">
          {title ?? (notFound ? t('Not found') : t('This did not load'))}
        </h3>
        <p className="mt-1 text-base text-muted-foreground">
          {errorMessage(error)}
        </p>
        {onRetry && !notFound && (
          <Button className="mt-4" onClick={onRetry}>
            <RotateCw aria-hidden="true" />
            {t('Try again')}
          </Button>
        )}
      </div>
    </div>
  );
}

export function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="grid gap-3 p-4" aria-busy="true" aria-label={t('Loading')}>
      {Array.from({ length: rows }, (_, index) => (
        <Skeleton key={index} className="h-9 w-full" />
      ))}
    </div>
  );
}

/** Loading → error → data, in one place, so no page forgets a state. */
export function QueryBoundary<T>({
  children,
  loading,
  query,
}: {
  children: (data: T) => ReactNode;
  loading?: ReactNode;
  query: UseQueryResult<T>;
}) {
  if (query.isPending) return <>{loading ?? <ListSkeleton />}</>;
  if (query.isError) {
    return (
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  return <>{children(query.data)}</>;
}
