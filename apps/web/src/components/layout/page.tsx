import { ChevronRight } from 'lucide-react';
import { Fragment, type ReactNode } from 'react';
import { Link } from 'react-router-dom';

import { cn } from '@/lib/utils';

export interface Crumb {
  label: string;
  to?: string;
}

/** Page frame: breadcrumb, title row with actions, then content. */
export function Page({
  actions,
  children,
  crumbs,
  description,
  title,
  titleSlot,
  width = 'default',
}: {
  actions?: ReactNode;
  children: ReactNode;
  crumbs?: Crumb[];
  description?: ReactNode;
  title: string;
  /** Inline content after the title, e.g. a status badge. */
  titleSlot?: ReactNode;
  width?: 'narrow' | 'default' | 'wide';
}) {
  // Centred in the space beside the sidebar so wide screens stay balanced.
  return (
    <div
      className={cn(
        'mx-auto w-full px-4 py-6 sm:px-6 lg:px-8',
        width === 'narrow' && 'max-w-3xl',
        width === 'default' && 'max-w-7xl',
        width === 'wide' && 'max-w-[90rem]',
      )}
    >
      {crumbs && crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-2">
          <ol className="flex flex-wrap items-center gap-1 text-sm text-muted-foreground">
            {crumbs.map((crumb, index) => (
              <Fragment key={`${crumb.label}-${index}`}>
                {index > 0 && (
                  <ChevronRight className="size-3.5" aria-hidden="true" />
                )}
                <li>
                  {crumb.to ? (
                    <Link to={crumb.to} className="hover:text-foreground">
                      {crumb.label}
                    </Link>
                  ) : (
                    <span aria-current="page">{crumb.label}</span>
                  )}
                </li>
              </Fragment>
            ))}
          </ol>
        </nav>
      )}
      <header className="mb-6 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-2xl font-semibold">{title}</h1>
            {titleSlot}
          </div>
          {description && (
            <p className="mt-1 max-w-2xl text-base text-muted-foreground">
              {description}
            </p>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </header>
      {children}
    </div>
  );
}
