import { forwardRef, type InputHTMLAttributes } from 'react';

import { Skeleton } from '@/components/ui/misc';
import { useAssetInfo } from '@/lib/api/chains';
import type { Asset } from '@/lib/api/types';
import { t } from '@/lib/i18n';
import { formatUnits } from '@/lib/money';
import { cn } from '@/lib/utils';

/** "Sepolia · TEST": the network and test label that travel with every amount. */
export function NetworkTag({
  asset,
  className,
}: {
  asset?: Asset;
  className?: string;
}) {
  const info = useAssetInfo(asset);
  if (!info) return null;
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 whitespace-nowrap text-xs text-subtle-foreground',
        className,
      )}
    >
      {info.chain.name}
      {info.asset.isTest && (
        <span className="rounded-sm border border-warning-border bg-warning-muted px-1 font-medium text-warning-foreground">
          {t('TEST')}
        </span>
      )}
    </span>
  );
}

/**
 * The only way an amount is rendered (NFR-UX-03).
 *
 * `context="inline"` shows value, symbol, network and the TEST label.
 * `context="column"` shows value and symbol only: use it in a table whose
 * column header is `<AmountHeader />`, which carries the network and label.
 */
export function Amount({
  asset,
  className,
  context = 'inline',
  muted,
  sign,
  size = 'md',
  value,
}: {
  asset?: Asset;
  className?: string;
  context?: 'inline' | 'column';
  muted?: boolean;
  sign?: '+' | '-';
  size?: 'sm' | 'md' | 'lg' | 'xl';
  value: string | bigint;
}) {
  const info = useAssetInfo(asset);
  if (!info) return <Skeleton className="inline-block h-4 w-24 align-middle" />;
  return (
    <span
      className={cn(
        'inline-flex items-baseline gap-1.5 whitespace-nowrap',
        className,
      )}
    >
      <span
        className={cn(
          'num font-medium',
          muted ? 'text-muted-foreground' : 'text-foreground',
          size === 'sm' && 'text-sm',
          size === 'md' && 'text-base',
          size === 'lg' && 'text-xl',
          size === 'xl' && 'text-display font-semibold',
        )}
      >
        {sign}
        {formatUnits(value, info.asset.decimals)}
      </span>
      <span
        className={cn(
          'text-muted-foreground',
          size === 'xl' || size === 'lg' ? 'text-base' : 'text-xs',
        )}
      >
        {info.asset.symbol}
      </span>
      {context === 'inline' && <NetworkTag asset={info.asset} />}
    </span>
  );
}

/** Header for an amount column: "Amount · USDC · Sepolia TEST". */
export function AmountHeader({ label = 'Amount' }: { label?: string }) {
  const info = useAssetInfo();
  return (
    <span className="inline-flex items-center gap-1.5">
      {t(label)}
      {info && (
        <>
          <span aria-hidden="true">·</span>
          {info.asset.symbol}
          <NetworkTag asset={info.asset} />
        </>
      )}
    </span>
  );
}

/**
 * Text input for an amount in display units. The form keeps the string;
 * convert with `parseUnits` (bigint, never a float — M16-D6).
 */
export const AmountInput = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & { asset?: Asset }
>(({ asset, className, ...props }, ref) => {
  const info = useAssetInfo(asset);
  return (
    <div
      className={cn(
        'flex h-9 items-center rounded-md border border-border-strong bg-surface focus-within:ring-2 focus-within:ring-ring has-[[aria-invalid=true]]:border-danger',
        className,
      )}
    >
      <input
        ref={ref}
        inputMode="decimal"
        autoComplete="off"
        placeholder="0.00"
        className="num h-full min-w-0 flex-1 rounded-md bg-transparent px-3 text-right text-base focus-visible:ring-0 focus-visible:ring-offset-0"
        {...props}
      />
      <span className="flex items-center gap-1.5 border-l px-2.5 text-sm text-muted-foreground">
        {info?.asset.symbol}
        <NetworkTag asset={info?.asset} />
      </span>
    </div>
  );
});
AmountInput.displayName = 'AmountInput';
