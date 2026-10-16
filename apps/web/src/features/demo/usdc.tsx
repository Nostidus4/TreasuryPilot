import { cn } from '@/lib/utils';

import { fmt, fmt2 } from './format';

/** An amount in the synthetic asset: no network, no explorer, just the figure and USDC. */
export function Usdc({
  className,
  approx,
  value,
  fixed,
}: {
  className?: string;
  approx?: boolean;
  value: string | bigint;
  fixed?: boolean;
}) {
  return (
    <span
      className={cn(
        'inline-flex items-baseline gap-1.5 whitespace-nowrap',
        className,
      )}
    >
      <span className="num font-medium text-foreground">
        {approx && '≈'}
        {fixed ? fmt2(value) : fmt(value)}
      </span>
      <span className="text-xs text-muted-foreground">USDC</span>
    </span>
  );
}
