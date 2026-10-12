import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from 'react';

import { cn } from '@/lib/utils';

export function Table({
  className,
  ...props
}: HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="w-full overflow-x-auto">
      <table
        className={cn('w-full border-collapse text-sm', className)}
        {...props}
      />
    </div>
  );
}

export function TableHeader(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <thead {...props} />;
}

export function TableBody(props: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody {...props} />;
}

export function TableRow({
  className,
  ...props
}: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn(
        'border-b last:border-0 data-[clickable=true]:cursor-pointer data-[clickable=true]:hover:bg-surface-muted data-[selected=true]:bg-primary-muted',
        className,
      )}
      {...props}
    />
  );
}

export function TableHead({
  align,
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement> & { align?: 'left' | 'right' }) {
  return (
    <th
      scope="col"
      className={cn(
        'sticky top-0 z-10 h-9 whitespace-nowrap border-b bg-surface-muted px-3 text-xs font-medium text-muted-foreground first:pl-4 last:pr-4',
        align === 'right' ? 'text-right' : 'text-left',
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({
  align,
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement> & { align?: 'left' | 'right' }) {
  return (
    <td
      className={cn(
        'h-11 px-3 py-2 align-middle first:pl-4 last:pr-4',
        align === 'right' && 'text-right',
        className,
      )}
      {...props}
    />
  );
}
