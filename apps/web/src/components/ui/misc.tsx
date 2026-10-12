import { cva, type VariantProps } from 'class-variance-authority';
import {
  CircleAlert,
  CircleCheck,
  Info,
  Sparkles,
  TriangleAlert,
} from 'lucide-react';
import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/utils';

export function Separator({ className }: { className?: string }) {
  return <div role="separator" className={cn('h-px bg-border', className)} />;
}

export function Skeleton({
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      aria-hidden="true"
      className={cn('block animate-pulse rounded-md bg-muted', className)}
      {...props}
    />
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-sm border bg-surface-muted px-1 font-sans text-xs text-muted-foreground">
      {children}
    </kbd>
  );
}

export function Avatar({
  className,
  name,
}: {
  className?: string;
  name: string;
}) {
  const initials = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('');
  return (
    <span
      aria-hidden="true"
      className={cn(
        'grid size-7 shrink-0 place-items-center rounded-full border bg-surface-muted text-xs font-medium text-muted-foreground',
        className,
      )}
    >
      {initials}
    </span>
  );
}

const alertVariants = cva('flex gap-3 rounded-lg border p-3 text-base', {
  variants: {
    tone: {
      info: 'border-info-border bg-info-muted text-info-foreground',
      success: 'border-success-border bg-success-muted text-success-foreground',
      warning: 'border-warning-border bg-warning-muted text-warning-foreground',
      danger: 'border-danger-border bg-danger-muted text-danger-foreground',
      neutral: 'border-border bg-surface-muted text-foreground',
      ai: 'border-ai-border bg-ai-muted text-ai-foreground',
    },
  },
  defaultVariants: { tone: 'info' },
});

const alertIcons = {
  info: Info,
  success: CircleCheck,
  warning: TriangleAlert,
  danger: CircleAlert,
  neutral: Info,
  ai: Sparkles,
};

export function Alert({
  action,
  children,
  className,
  title,
  tone = 'info',
  ...props
}: Omit<HTMLAttributes<HTMLDivElement>, 'title'> &
  VariantProps<typeof alertVariants> & {
    action?: ReactNode;
    title?: ReactNode;
  }) {
  const Icon = alertIcons[tone ?? 'info'];
  return (
    <div
      role={tone === 'danger' ? 'alert' : 'status'}
      className={cn(alertVariants({ tone }), className)}
      {...props}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && (
          <div className={cn('text-sm', title && 'mt-0.5')}>{children}</div>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
