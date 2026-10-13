import { Check, Copy, ExternalLink } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Tooltip } from '@/components/ui/menus';
import { useChain } from '@/lib/api/chains';
import { countdown, shortAddress, shortHash } from '@/lib/format';
import { t } from '@/lib/i18n';
import { cn } from '@/lib/utils';

function CopyButton({ value, what }: { value: string; what: string }) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);
  return (
    <button
      type="button"
      aria-label={t('Copy {{what}}', { what })}
      className="grid size-5 place-items-center rounded-sm text-subtle-foreground hover:bg-muted hover:text-foreground"
      onClick={(event) => {
        event.stopPropagation();
        void navigator.clipboard?.writeText(value).then(() => setCopied(true));
      }}
    >
      {copied ? (
        <Check className="size-3 text-success" aria-hidden="true" />
      ) : (
        <Copy className="size-3" aria-hidden="true" />
      )}
    </button>
  );
}

function ExplorerLink({ path, what }: { path: string; what: string }) {
  const chain = useChain();
  if (!chain) return null;
  return (
    <a
      href={`${chain.explorerUrl}/${path}`}
      target="_blank"
      rel="noreferrer"
      aria-label={t('Open {{what}} in the block explorer', { what })}
      className="grid size-5 place-items-center rounded-sm text-subtle-foreground hover:bg-muted hover:text-foreground"
      onClick={(event) => event.stopPropagation()}
    >
      <ExternalLink className="size-3" aria-hidden="true" />
    </a>
  );
}

/** An address: optional human name, shortened hex, copy, explorer link. */
export function Address({
  address,
  className,
  full,
  label,
}: {
  address: string;
  className?: string;
  full?: boolean;
  label?: string;
}) {
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', className)}>
      {label && <span className="truncate font-medium">{label}</span>}
      <Tooltip content={<span className="num break-all">{address}</span>}>
        <span
          className={cn(
            'num text-sm',
            label ? 'text-muted-foreground' : 'text-foreground',
            full && 'break-all',
          )}
        >
          {full ? address : shortAddress(address)}
        </span>
      </Tooltip>
      <CopyButton value={address} what={t('address')} />
      <ExplorerLink path={`address/${address}`} what={t('address')} />
    </span>
  );
}

export function TxHash({ hash }: { hash: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="num text-sm text-muted-foreground">
        {shortHash(hash)}
      </span>
      <CopyButton value={hash} what={t('transaction hash')} />
      <ExplorerLink path={`tx/${hash}`} what={t('transaction')} />
    </span>
  );
}

/** Live countdown, e.g. a payee cooling period. Renders nothing once past. */
export function CountdownChip({
  label,
  until,
}: {
  label: string;
  until: string;
}) {
  const [, setNow] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setNow((value) => value + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const remaining = countdown(until);
  if (!remaining) return null;
  return (
    <Badge tone="warning">
      {label} <span className="num">{remaining}</span>
    </Badge>
  );
}
