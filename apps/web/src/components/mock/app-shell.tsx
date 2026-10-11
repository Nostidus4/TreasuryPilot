import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { NavLink } from 'react-router-dom';
import {
  ChevronDown,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  ShieldCheck,
  X,
} from 'lucide-react';

import {
  mockNavigation,
  mockUser,
  mockWorkspace,
  type MockNavigationItem,
  type MockPageId,
  type MockUser,
  type MockWorkspace,
} from '@/lib/mock-data';
import { cn } from '@/lib/utils';

import { BrandMark, IconButton, StatusBadge } from './primitives';

export interface MockAppShellProps {
  children: ReactNode;
  activePage: MockPageId;
  navigation?: readonly MockNavigationItem[];
  workspace?: MockWorkspace;
  user?: MockUser;
  className?: string;
}

const groupLabels: Record<MockNavigationItem['group'], string> = {
  workspace: 'Workspace',
  treasury: 'Treasury controls',
};

function NavigationList({
  items,
  activePage,
  collapsed,
  onLinkClick,
}: {
  items: readonly MockNavigationItem[];
  activePage: MockPageId;
  collapsed: boolean;
  onLinkClick?: () => void;
}) {
  const groups = Array.from(new Set(items.map((item) => item.group)));

  return (
    <nav aria-label="Treasury workspace navigation" className="min-w-0">
      {groups.map((group) => (
        <div key={group} className="mb-5 last:mb-0">
          {!collapsed && (
            <p className="mb-2 px-3 text-[10px] font-bold uppercase tracking-[0.16em] text-slate-400">
              {groupLabels[group]}
            </p>
          )}
          <ul className="grid gap-1">
            {items
              .filter((item) => item.group === group)
              .map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.id}>
                    <NavLink
                      to={item.to}
                      end={item.id === 'dashboard'}
                      onClick={onLinkClick}
                      aria-label={collapsed ? item.label : undefined}
                      title={collapsed ? item.label : undefined}
                      className={({ isActive }) => {
                        const active = isActive && item.id === activePage;
                        return cn(
                          'group relative flex h-10 w-full items-center gap-3 rounded-xl px-3 text-left text-[13px] font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2',
                          collapsed && 'justify-center px-0',
                          active
                            ? 'bg-blue-50 text-blue-800'
                            : 'text-slate-500 hover:bg-slate-50 hover:text-slate-900',
                        );
                      }}
                    >
                      {({ isActive }) => {
                        const active = isActive && item.id === activePage;
                        return (
                          <>
                            {active && (
                              <span
                                aria-hidden="true"
                                className="absolute -left-3 h-5 w-[3px] rounded-r-full bg-blue-700"
                              />
                            )}
                            <Icon
                              aria-hidden="true"
                              className={cn(
                                'shrink-0',
                                active
                                  ? 'text-blue-700'
                                  : 'text-slate-400 group-hover:text-slate-600',
                              )}
                              size={18}
                              strokeWidth={1.9}
                            />
                            {!collapsed && (
                              <span className="min-w-0 flex-1 truncate">
                                {item.label}
                              </span>
                            )}
                          </>
                        );
                      }}
                    </NavLink>
                  </li>
                );
              })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

function Sidebar({
  items,
  activePage,
  collapsed,
  mobile = false,
  onClose,
  workspace,
}: {
  items: readonly MockNavigationItem[];
  activePage: MockPageId;
  collapsed: boolean;
  mobile?: boolean;
  onClose?: () => void;
  workspace: MockWorkspace;
}) {
  return (
    <aside
      aria-label="TreasuryPilot navigation"
      className={cn(
        'flex h-full min-h-0 flex-col border-r border-slate-200/80 bg-white',
        mobile
          ? 'w-[min(20rem,calc(100vw-2rem))]'
          : 'sticky top-0 hidden h-screen shrink-0 lg:flex',
        !mobile && (collapsed ? 'w-[76px]' : 'w-[252px]'),
      )}
    >
      <div
        className={cn(
          'flex h-[76px] shrink-0 items-center border-b border-slate-100 px-4',
          collapsed && !mobile && 'justify-center px-2',
        )}
      >
        <NavLink
          to="/mock"
          aria-label="TreasuryPilot overview"
          className="min-w-0 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
        >
          <BrandMark compact={collapsed && !mobile} />
        </NavLink>
        {mobile && (
          <IconButton
            className="ml-auto"
            label="Close navigation"
            onClick={onClose}
          >
            <X size={19} />
          </IconButton>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-5">
        <NavigationList
          items={items}
          activePage={activePage}
          collapsed={collapsed && !mobile}
          onLinkClick={onClose}
        />
      </div>
      <div
        className={cn(
          'shrink-0 border-t border-slate-100 p-3',
          collapsed && !mobile && 'px-2',
        )}
      >
        <div
          className={cn(
            'rounded-xl border border-blue-100 bg-blue-50/70 p-3',
            collapsed &&
              !mobile &&
              'flex justify-center border-transparent bg-transparent p-1',
          )}
        >
          <ShieldCheck
            aria-hidden="true"
            className="mb-2 text-blue-700"
            size={17}
          />
          {(!collapsed || mobile) && (
            <>
              <p className="text-[11px] font-bold text-blue-950">
                Execution boundary
              </p>
              <p className="mt-1 text-[10px] leading-4 text-blue-900/75">
                People approve. Policy checks. On-chain Safe rules enforce.
              </p>
              <p className="mt-2 border-t border-blue-100 pt-2 text-[10px] font-semibold text-blue-800">
                {workspace.network} · fictional data
              </p>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}

export function MockAppShell({
  children,
  activePage,
  navigation = mockNavigation,
  workspace = mockWorkspace,
  user = mockUser,
  className,
}: MockAppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const backgroundRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!mobileOpen) return undefined;

    const returnFocus =
      triggerRef.current ??
      (document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null);
    const dialog = dialogRef.current;
    const background = backgroundRef.current;
    const previousOverflow = document.body.style.overflow;
    const getFocusableItems = () =>
      Array.from(
        dialog?.querySelectorAll<HTMLElement>(
          'button:not([disabled]):not([tabindex="-1"]), a[href]:not([tabindex="-1"]), input:not([disabled]):not([tabindex="-1"]), select:not([disabled]):not([tabindex="-1"]), textarea:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])',
        ) ?? [],
      );

    document.body.style.overflow = 'hidden';
    background?.setAttribute('inert', '');
    getFocusableItems()[0]?.focus();

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileOpen(false);
        return;
      }
      if (event.key !== 'Tab') return;

      const focusableItems = getFocusableItems();
      const first = focusableItems[0];
      const last = focusableItems[focusableItems.length - 1];
      if (!first || !last) {
        event.preventDefault();
        dialog?.focus();
        return;
      }
      if (!dialog?.contains(document.activeElement)) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
      } else if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', onKeyDown);
    return () => {
      window.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      background?.removeAttribute('inert');
      returnFocus?.focus();
    };
  }, [mobileOpen]);

  return (
    <div
      className={cn(
        'min-h-screen bg-[#f5f8fd] text-slate-900 antialiased',
        className,
      )}
    >
      <div
        ref={backgroundRef}
        className="flex min-h-screen"
        aria-hidden={mobileOpen || undefined}
      >
        <a
          href="#main-content"
          className="sr-only z-[60] rounded-lg bg-white px-3 py-2 text-sm font-semibold text-blue-800 focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          Skip to main content
        </a>
        <Sidebar
          items={navigation}
          activePage={activePage}
          collapsed={collapsed}
          workspace={workspace}
        />
        <div className="min-w-0 flex-1">
          <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/95 backdrop-blur">
            <div className="flex h-[68px] items-center gap-3 px-4 sm:px-6 xl:px-8">
              <IconButton
                className="hidden lg:inline-grid"
                label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                onClick={() => setCollapsed((current) => !current)}
              >
                {collapsed ? (
                  <PanelLeftOpen size={19} />
                ) : (
                  <PanelLeftClose size={19} />
                )}
              </IconButton>
              <IconButton
                className="lg:hidden"
                label="Open navigation"
                onClick={() => setMobileOpen(true)}
                ref={triggerRef}
              >
                <Menu size={20} />
              </IconButton>
              <NavLink
                to="/mock"
                aria-label="TreasuryPilot overview"
                className="rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 lg:hidden"
              >
                <BrandMark />
              </NavLink>
              <div className="ml-auto flex min-w-0 items-center gap-2 sm:gap-3">
                <div className="hidden min-w-0 items-center gap-2.5 rounded-xl px-2 py-1.5 md:flex">
                  <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-blue-50 text-xs font-bold text-blue-800">
                    {workspace.initials}
                  </span>
                  <span className="min-w-0">
                    <span className="block max-w-36 truncate text-xs font-bold text-slate-800">
                      {workspace.name}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-slate-500">
                      {workspace.network}
                    </span>
                  </span>
                  <ChevronDown
                    aria-hidden="true"
                    className="shrink-0 text-slate-400"
                    size={14}
                  />
                </div>
                <StatusBadge tone="info" dot>
                  {workspace.network}
                </StatusBadge>
                <StatusBadge tone="neutral" className="hidden sm:inline-flex">
                  {workspace.environment}
                </StatusBadge>
                <span className="hidden h-8 w-px bg-slate-200 sm:block" />
                <span
                  role="img"
                  aria-label={`${user.name}, ${user.role}`}
                  className="grid size-8 shrink-0 place-items-center rounded-full bg-gradient-to-br from-blue-100 to-indigo-200 text-[10px] font-extrabold text-blue-950"
                >
                  {user.initials}
                </span>
              </div>
            </div>
          </header>
          <main
            id="main-content"
            tabIndex={-1}
            className="mx-auto w-full max-w-[1600px] px-4 py-6 sm:px-6 sm:py-8 xl:px-9"
          >
            <div className="mb-5 flex items-center gap-2 rounded-xl border border-blue-100 bg-white/75 px-3.5 py-2.5 text-[11px] leading-5 text-slate-600 shadow-sm sm:hidden">
              <ShieldCheck
                aria-hidden="true"
                className="shrink-0 text-blue-700"
                size={15}
              />
              <span>
                <strong className="font-bold text-slate-800">
                  Fictional {workspace.network} preview.
                </strong>{' '}
                No wallet actions are performed here.
              </span>
            </div>
            {children}
          </main>
          <footer className="mx-auto flex max-w-[1600px] flex-col gap-2 border-t border-slate-200/70 px-4 py-4 text-[10px] text-slate-500 sm:px-6 xl:px-9">
            <span>
              Human approval authorizes each payment. Policy checks validate the
              plan. On-chain Safe rules enforce execution.
            </span>
            <span>
              Fictional Sepolia TEST snapshot · No wallet signatures or
              transactions are created or sent from this preview.
            </span>
          </footer>
        </div>
      </div>

      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            className="absolute inset-0 cursor-default bg-slate-950/45 backdrop-blur-[2px]"
            onClick={() => setMobileOpen(false)}
          />
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Treasury workspace navigation"
            data-mobile-navigation-dialog
            tabIndex={-1}
            className="absolute inset-y-0 left-0 shadow-2xl shadow-slate-950/20"
          >
            <Sidebar
              items={navigation}
              activePage={activePage}
              collapsed={false}
              mobile
              onClose={() => setMobileOpen(false)}
              workspace={workspace}
            />
          </div>
        </div>
      )}
    </div>
  );
}
