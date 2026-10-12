import {
  ArrowRight,
  FileText,
  Lock,
  LockOpen,
  Minus,
  ZoomIn,
  ZoomOut,
} from 'lucide-react';
import { useState, type ReactNode } from 'react';

import { Amount } from '@/components/domain/amount';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { DiffEntry } from '@/lib/api/types';
import { t } from '@/lib/i18n';
import { ratioPercent, toBigInt } from '@/lib/money';
import { cn } from '@/lib/utils';

/** Label/value rows. The base of every "details" panel. */
export function KeyValueList({
  className,
  items,
}: {
  className?: string;
  items: Array<{ label: ReactNode; value: ReactNode; hint?: ReactNode }>;
}) {
  return (
    <dl className={cn('divide-y text-base', className)}>
      {items.map((item, index) => (
        <div
          key={index}
          className="flex items-start justify-between gap-4 py-2 first:pt-0 last:pb-0"
        >
          <dt className="text-muted-foreground">
            {item.label}
            {item.hint && (
              <span className="block text-xs text-subtle-foreground">
                {item.hint}
              </span>
            )}
          </dt>
          <dd className="min-w-0 text-right">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * A balance against its minimum buffer and target on one track.
 * The fill is the balance; ticks mark the buffer and the target.
 */
export function BalanceMeter({
  balance,
  buffer,
  target,
}: {
  balance: string;
  buffer: string;
  target: string;
}) {
  const scale = [balance, buffer, target]
    .map(toBigInt)
    .reduce((max, value) => (value > max ? value : max), 1n);
  const top = (scale * 115n) / 100n;
  const belowBuffer = toBigInt(balance) < toBigInt(buffer);
  const belowTarget = toBigInt(balance) < toBigInt(target);
  return (
    <div>
      <div className="relative h-2 rounded-full bg-muted">
        <div
          className={cn(
            'h-full rounded-full',
            belowBuffer
              ? 'bg-danger'
              : belowTarget
                ? 'bg-warning'
                : 'bg-success',
          )}
          style={{ width: `${ratioPercent(balance, top)}%` }}
        />
        {[
          { value: buffer, label: t('Minimum buffer') },
          { value: target, label: t('Target') },
        ].map((mark) => (
          <span
            key={mark.label}
            title={mark.label}
            className="absolute -top-1 h-4 w-0.5 rounded-full bg-foreground/70"
            style={{ left: `${ratioPercent(mark.value, top)}%` }}
          />
        ))}
      </div>
      <div className="mt-2 flex flex-wrap justify-between gap-x-4 gap-y-1 text-xs text-muted-foreground">
        <span>
          {t('Minimum buffer')}{' '}
          <Amount value={buffer} size="sm" context="column" muted />
        </span>
        <span>
          {t('Target')}{' '}
          <Amount value={target} size="sm" context="column" muted />
        </span>
      </div>
    </div>
  );
}

/** Used-of-limit bar, e.g. today's budget against the daily limit. */
export function UsageBar({
  label,
  limit,
  used,
}: {
  label: string;
  limit: string;
  used: string;
}) {
  const percent = ratioPercent(used, limit);
  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">
          <Amount value={used} size="sm" context="column" /> {t('of')}{' '}
          <Amount value={limit} size="sm" context="column" muted />
        </span>
      </div>
      <div
        className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(percent)}
      >
        <div
          className={cn(
            'h-full rounded-full',
            percent >= 90
              ? 'bg-danger'
              : percent >= 70
                ? 'bg-warning'
                : 'bg-primary',
          )}
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

const directionMeta = {
  LOOSER: { label: 'Looser', tone: 'warning', icon: LockOpen },
  STRICTER: { label: 'Stricter', tone: 'success', icon: Lock },
  NEUTRAL: { label: 'Changed', tone: 'neutral', icon: Minus },
} as const;

/** Before → after rows, each marked as loosening or tightening control. */
export function DiffView({
  diff,
  emptyText,
}: {
  diff: DiffEntry[];
  emptyText?: string;
}) {
  if (diff.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        {emptyText ?? t('No changes against the active version.')}
      </p>
    );
  }
  return (
    <ul className="divide-y rounded-lg border">
      {diff.map((entry) => {
        const meta = directionMeta[entry.direction];
        const Icon = meta.icon;
        return (
          <li
            key={entry.field}
            className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2"
          >
            <span className="w-full text-sm font-medium sm:w-44">
              {entry.field}
            </span>
            <span className="num text-sm text-muted-foreground line-through">
              {entry.before}
            </span>
            <ArrowRight
              className="size-3.5 text-subtle-foreground"
              aria-hidden="true"
            />
            <span className="num text-sm font-medium">{entry.after}</span>
            <Badge tone={meta.tone} className="ml-auto">
              <Icon aria-hidden="true" />
              {t(meta.label)}
            </Badge>
          </li>
        );
      })}
    </ul>
  );
}

/** PDF or image viewer for an invoice. Untrusted content: never as HTML. */
export function DocumentViewer({
  document,
}: {
  document?: { name: string; mime: string; url: string };
}) {
  const [zoom, setZoom] = useState(100);
  if (!document) {
    return (
      <div className="grid h-full min-h-64 place-items-center rounded-lg border border-dashed bg-surface-muted p-6 text-center">
        <div>
          <FileText
            className="mx-auto size-6 text-subtle-foreground"
            aria-hidden="true"
          />
          <p className="mt-2 text-base font-medium">{t('No document')}</p>
          <p className="text-sm text-muted-foreground">
            {t('This request was entered manually.')}
          </p>
        </div>
      </div>
    );
  }
  const isImage = document.mime.startsWith('image/');
  return (
    <div className="flex h-full min-h-80 flex-col overflow-hidden rounded-lg border bg-surface-muted">
      <div className="flex items-center gap-2 border-b bg-surface px-3 py-1.5">
        <FileText className="size-4 text-muted-foreground" aria-hidden="true" />
        <p className="min-w-0 flex-1 truncate text-sm font-medium">
          {document.name}
        </p>
        {isImage && (
          <>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t('Zoom out')}
              disabled={zoom <= 50}
              onClick={() => setZoom((value) => value - 25)}
            >
              <ZoomOut aria-hidden="true" />
            </Button>
            <span className="num w-10 text-center text-xs text-muted-foreground">
              {zoom}%
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label={t('Zoom in')}
              disabled={zoom >= 200}
              onClick={() => setZoom((value) => value + 25)}
            >
              <ZoomIn aria-hidden="true" />
            </Button>
          </>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        {!document.url ? (
          <div className="grid h-full min-h-64 place-items-center p-6 text-center text-sm text-muted-foreground">
            {t(
              'The preview is not available in the mock API. With the real API the stored file opens here.',
            )}
          </div>
        ) : isImage ? (
          <img
            src={document.url}
            alt={t('Uploaded invoice {{name}}', { name: document.name })}
            className="mx-auto"
            style={{ width: `${zoom}%`, maxWidth: 'none' }}
          />
        ) : (
          <object
            data={document.url}
            type={document.mime}
            aria-label={document.name}
            className="h-full min-h-[32rem] w-full"
          >
            <p className="p-6 text-sm text-muted-foreground">
              {t('This browser cannot display the file inline.')}{' '}
              <a
                className="text-primary underline"
                href={document.url}
                target="_blank"
                rel="noreferrer"
              >
                {t('Open it in a new tab')}
              </a>
            </p>
          </object>
        )}
      </div>
    </div>
  );
}
