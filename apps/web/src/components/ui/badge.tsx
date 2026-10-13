import { cva, type VariantProps } from 'class-variance-authority';
import { forwardRef, type HTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 py-0.5 text-xs font-medium [&_svg]:size-3 [&_svg]:shrink-0',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-surface-muted text-muted-foreground',
        success:
          'border-success-border bg-success-muted text-success-foreground',
        warning:
          'border-warning-border bg-warning-muted text-warning-foreground',
        danger: 'border-danger-border bg-danger-muted text-danger-foreground',
        info: 'border-info-border bg-info-muted text-info-foreground',
        ai: 'border-ai-border bg-ai-muted text-ai-foreground',
        outline: 'border-border-strong bg-transparent text-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
);

export type Tone = NonNullable<VariantProps<typeof badgeVariants>['tone']>;

export const Badge = forwardRef<
  HTMLSpanElement,
  HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>
>(({ className, tone, ...props }, ref) => (
  <span
    ref={ref}
    className={cn(badgeVariants({ tone }), className)}
    {...props}
  />
));
Badge.displayName = 'Badge';
