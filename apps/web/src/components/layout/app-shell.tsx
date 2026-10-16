import {
  ArrowLeftRight,
  BarChart3,
  BookOpen,
  Building2,
  Check,
  ChevronsUpDown,
  CircleDollarSign,
  ClipboardCheck,
  FileText,
  Fuel,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  Monitor,
  Moon,
  PenLine,
  Scale,
  Search,
  ShieldCheck,
  Sparkles,
  Sun,
  TriangleAlert,
  Users,
  Wallet as WalletIcon,
  Workflow,
  type LucideIcon,
} from 'lucide-react';
import { Suspense, useEffect, useState, type ReactNode } from 'react';
import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom';

import { CommandMenu } from '@/components/layout/command-menu';
import { ConnectWalletDialog } from '@/components/domain/signing';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogTitle, SheetContent } from '@/components/ui/dialog';
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Tooltip,
} from '@/components/ui/menus';
import { Avatar, Kbd, Skeleton } from '@/components/ui/misc';
import { useMe, useSignOut } from '@/features/auth/api';
import { CopilotPanel } from '@/features/copilot/copilot-panel';
import { NotificationBell } from '@/features/notifications/notification-bell';
import { useOrgScope } from '@/features/orgs/org-scope';
import { useTreasury } from '@/features/treasury/api';
import { StatusBanners } from '@/features/treasury/status-banner';
import type { Role } from '@/lib/api/types';
import { mockApiEnabled } from '@/lib/env';
import { shortAddress } from '@/lib/format';
import { t } from '@/lib/i18n';
import { roleLabels } from '@/lib/status';
import { useTheme } from '@/lib/theme';
import { useWallet } from '@/lib/wallet/wallet-context';
import { cn } from '@/lib/utils';

interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  end?: boolean;
  count?: number;
  roles?: Role[];
  needsTreasury?: boolean;
}

function useNavigation(): Array<{ label?: string; items: NavItem[] }> {
  const scope = useOrgScope();
  const treasury = useTreasury(scope.orgId, scope.treasuryId);
  const queues = treasury.data?.queues;
  const { base, tBase } = scope;
  return [
    {
      items: [
        {
          label: t('Overview'),
          to: scope.treasuryId ? tBase : base,
          icon: LayoutDashboard,
          end: true,
        },
      ],
    },
    {
      label: t('Inbox'),
      items: [
        {
          label: t('Approvals'),
          to: `${base}/approvals`,
          icon: ClipboardCheck,
          count: queues?.approvals,
          roles: ['APR', 'OWN'],
        },
        {
          label: t('Governance'),
          to: `${base}/governance`,
          icon: PenLine,
          count: queues?.governance,
        },
        {
          label: t('Review'),
          to: `${base}/review`,
          icon: TriangleAlert,
          count: queues?.review,
        },
      ],
    },
    {
      label: t('Payments'),
      items: [
        { label: t('Requests'), to: `${base}/requests`, icon: FileText },
        {
          label: t('Plans'),
          to: `${tBase}/plans`,
          icon: Workflow,
          needsTreasury: true,
        },
        {
          label: t('Reconciliation'),
          to: `${base}/reconciliation`,
          icon: ArrowLeftRight,
          count: queues?.reconciliation,
          roles: ['FIN', 'AUD', 'OWN'],
        },
      ],
    },
    {
      label: t('Controls'),
      items: [
        {
          label: t('Mandate'),
          to: `${tBase}/mandate`,
          icon: Scale,
          needsTreasury: true,
        },
        {
          label: t('Payees'),
          to: `${tBase}/payees`,
          icon: ShieldCheck,
          needsTreasury: true,
        },
        {
          label: t('Fees'),
          to: `${tBase}/settings/fees`,
          icon: Fuel,
          needsTreasury: true,
        },
      ],
    },
    {
      label: t('Insights'),
      items: [
        {
          label: t('Metrics'),
          to: `${base}/metrics`,
          icon: BarChart3,
          roles: ['OWN', 'FIN', 'AUD'],
        },
      ],
    },
    {
      label: t('Settings'),
      items: [
        { label: t('Members'), to: `${base}/members`, icon: Users },
        { label: t('Wallets'), to: '/me/wallets', icon: WalletIcon },
        { label: t('Security'), to: '/me/security', icon: ShieldCheck },
        {
          label: t('Setup checklist'),
          to: `${base}/onboarding`,
          icon: ListChecks,
        },
      ],
    },
  ];
}

function OrgSwitcher() {
  const scope = useOrgScope();
  const me = useMe();
  const navigate = useNavigate();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="flex w-full items-center gap-2.5 rounded-md p-1.5 text-left hover:bg-muted">
        <span className="grid size-8 shrink-0 place-items-center rounded-md bg-primary text-primary-foreground">
          <CircleDollarSign className="size-4" aria-hidden="true" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-base font-semibold">
            {scope.org.name}
          </span>
          <span className="block truncate text-xs text-muted-foreground">
            {scope.org.treasuries.find((item) => item.id === scope.treasuryId)
              ?.name ?? t('No treasury yet')}
          </span>
        </span>
        <ChevronsUpDown
          className="size-4 text-subtle-foreground"
          aria-hidden="true"
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>{t('Organizations')}</DropdownMenuLabel>
        {me.data?.memberships.map((membership) => (
          <DropdownMenuItem
            key={membership.orgId}
            onSelect={() => navigate(`/o/${membership.orgId}`)}
          >
            <Building2 aria-hidden="true" />
            <span className="flex-1 truncate">{membership.orgName}</span>
            {membership.orgId === scope.orgId && <Check aria-hidden="true" />}
          </DropdownMenuItem>
        ))}
        {scope.org.treasuries.length > 1 && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuLabel>{t('Treasuries')}</DropdownMenuLabel>
            {scope.org.treasuries.map((treasury) => (
              <DropdownMenuItem
                key={treasury.id}
                onSelect={() => navigate(`${scope.base}/t/${treasury.id}`)}
              >
                <span className="flex-1 truncate">{treasury.name}</span>
                {treasury.id === scope.treasuryId && (
                  <Check aria-hidden="true" />
                )}
              </DropdownMenuItem>
            ))}
          </>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate('/orgs')}>
          {t('All organizations')}
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={() => navigate(`${scope.base}/treasuries/new`)}
        >
          {t('Add a treasury')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const scope = useOrgScope();
  const groups = useNavigation();
  return (
    <div className="flex h-full flex-col">
      <div className="border-b p-2.5">
        <OrgSwitcher />
      </div>
      <nav
        aria-label={t('Main')}
        className="min-h-0 flex-1 overflow-y-auto p-2.5"
      >
        {groups.map((group, index) => {
          const items = group.items.filter(
            (item) => !item.roles || scope.can(...item.roles),
          );
          if (items.length === 0) return null;
          return (
            <div key={group.label ?? index} className="mb-4 last:mb-0">
              {group.label && (
                <p className="mb-1 px-2 text-xs font-medium text-subtle-foreground">
                  {group.label}
                </p>
              )}
              <ul className="grid gap-0.5">
                {items.map((item) => {
                  const disabled = item.needsTreasury && !scope.treasuryId;
                  const Icon = item.icon;
                  const content = (
                    <>
                      <Icon className="size-4 shrink-0" aria-hidden="true" />
                      <span className="flex-1 truncate">{item.label}</span>
                      {item.count ? (
                        <span
                          className="num rounded-sm bg-muted px-1.5 text-xs font-medium text-foreground"
                          aria-label={t('{{count}} waiting', {
                            count: item.count,
                          })}
                        >
                          {item.count}
                        </span>
                      ) : null}
                    </>
                  );
                  return (
                    <li key={item.label}>
                      {disabled ? (
                        <Tooltip
                          content={t('Set up a treasury first')}
                          side="right"
                        >
                          <span
                            aria-disabled="true"
                            className="flex h-8 items-center gap-2.5 rounded-md px-2 text-base text-subtle-foreground/60"
                          >
                            {content}
                          </span>
                        </Tooltip>
                      ) : (
                        <NavLink
                          to={item.to}
                          end={item.end}
                          onClick={onNavigate}
                          className={({ isActive }) =>
                            cn(
                              'flex h-8 items-center gap-2.5 rounded-md px-2 text-base transition-colors',
                              isActive
                                ? 'bg-muted font-medium text-foreground'
                                : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                            )
                          }
                        >
                          {content}
                        </NavLink>
                      )}
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </nav>
      {import.meta.env.PROD && (
        <div className="border-t p-2.5">
          <a
            href={`${import.meta.env.BASE_URL}report/`}
            onClick={onNavigate}
            className="flex h-8 items-center gap-2.5 rounded-md px-2 text-base text-muted-foreground hover:bg-muted/60 hover:text-foreground"
          >
            <BookOpen className="size-4 shrink-0" aria-hidden="true" />
            <span>{t('Technical report')}</span>
          </a>
        </div>
      )}
    </div>
  );
}

function WalletChip() {
  const wallet = useWallet();
  const [open, setOpen] = useState(false);
  if (!wallet.address) {
    return (
      <>
        <Button size="sm" onClick={() => setOpen(true)}>
          <WalletIcon aria-hidden="true" />
          <span className="hidden sm:inline">{t('Connect wallet')}</span>
        </Button>
        <ConnectWalletDialog open={open} onOpenChange={setOpen} />
      </>
    );
  }
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" aria-label={t('Wallet')}>
          <span
            className="size-1.5 rounded-full bg-success"
            aria-hidden="true"
          />
          <span className="num">{shortAddress(wallet.address)}</span>
          {wallet.kind === 'demo' && (
            <Badge tone="warning" className="hidden sm:inline-flex">
              {t('Demo')}
            </Badge>
          )}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuLabel>
          {wallet.kind === 'demo' ? t('Demo signer') : t('Browser wallet')}
        </DropdownMenuLabel>
        <DropdownMenuItem asChild>
          <Link to="/me/wallets">{t('Linked wallets')}</Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => wallet.disconnect()}>
          {t('Disconnect')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const me = useMe();
  const scope = useOrgScope();
  const signOut = useSignOut();
  const navigate = useNavigate();
  const { theme, setTheme } = useTheme();
  const user = me.data?.user;
  if (!user) return null;
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className="rounded-full"
        aria-label={t('Account menu')}
      >
        <Avatar name={user.name} className="size-8" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-60">
        <div className="px-2 py-1.5">
          <p className="truncate text-base font-medium">{user.name}</p>
          <p className="truncate text-sm text-muted-foreground">{user.email}</p>
          <p className="mt-1.5 flex flex-wrap gap-1">
            {scope.roles.map((role) => (
              <Badge key={role}>{t(roleLabels[role])}</Badge>
            ))}
          </p>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>{t('Theme')}</DropdownMenuLabel>
        {(
          [
            ['light', t('Light'), Sun],
            ['dark', t('Dark'), Moon],
            ['system', t('System'), Monitor],
          ] as const
        ).map(([value, label, Icon]) => (
          <DropdownMenuCheckboxItem
            key={value}
            checked={theme === value}
            onCheckedChange={() => setTheme(value)}
          >
            <Icon aria-hidden="true" />
            {label}
          </DropdownMenuCheckboxItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuItem
          onSelect={() =>
            signOut.mutate(undefined, {
              onSuccess: () => navigate('/login', { replace: true }),
            })
          }
        >
          <LogOut aria-hidden="true" />
          {t('Sign out')}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const scope = useOrgScope();
  const location = useLocation();
  const [mobileNav, setMobileNav] = useState(false);
  const [commandOpen, setCommandOpen] = useState(false);
  const [copilotOpen, setCopilotOpen] = useState(false);

  useEffect(() => setMobileNav(false), [location.pathname]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        setCommandOpen((value) => !value);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  return (
    <div className="min-h-dvh bg-background">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2 focus:shadow-float"
      >
        {t('Skip to content')}
      </a>

      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r bg-surface lg:block">
        <Sidebar />
      </aside>

      <Dialog open={mobileNav} onOpenChange={setMobileNav}>
        <SheetContent side="left" width="sm" aria-describedby={undefined}>
          <DialogTitle className="sr-only">{t('Navigation')}</DialogTitle>
          <Sidebar onNavigate={() => setMobileNav(false)} />
        </SheetContent>
      </Dialog>

      <div className="lg:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b bg-surface/95 px-3 backdrop-blur sm:px-6">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            aria-label={t('Open navigation')}
            onClick={() => setMobileNav(true)}
          >
            <Menu aria-hidden="true" />
          </Button>
          <button
            type="button"
            onClick={() => setCommandOpen(true)}
            className="flex h-8 min-w-0 flex-1 items-center gap-2 rounded-md border bg-background px-2.5 text-left text-sm text-subtle-foreground hover:border-border-strong sm:max-w-xs"
          >
            <Search className="size-4 shrink-0" aria-hidden="true" />
            <span className="flex-1 truncate">{t('Search or jump to…')}</span>
            <span className="hidden sm:inline">
              <Kbd>⌘K</Kbd>
            </span>
          </button>
          <div className="ml-auto flex items-center gap-1.5">
            {mockApiEnabled && (
              <Tooltip
                content={t(
                  'Data comes from the in-browser mock API and resets on reload.',
                )}
              >
                <Badge tone="warning" className="hidden md:inline-flex">
                  {t('Mock API')}
                </Badge>
              </Tooltip>
            )}
            <Tooltip
              content={
                scope.live
                  ? t('Live updates connected')
                  : t('Live updates off — refreshing every 10 seconds')
              }
            >
              <span
                role="status"
                aria-label={
                  scope.live ? t('Live updates connected') : t('Polling')
                }
                className={cn(
                  'mx-1 hidden size-2 rounded-full sm:block',
                  scope.live ? 'bg-success' : 'bg-warning',
                )}
              />
            </Tooltip>
            <WalletChip />
            <Tooltip content={t('Treasury Copilot')}>
              <Button
                variant="ghost"
                size="icon"
                aria-label={t('Open Treasury Copilot')}
                onClick={() => setCopilotOpen(true)}
              >
                <Sparkles aria-hidden="true" />
              </Button>
            </Tooltip>
            <NotificationBell />
            <UserMenu />
          </div>
        </header>

        <StatusBanners />

        <main id="main" tabIndex={-1} className="focus-visible:ring-0">
          {/* Screens load as separate chunks; the shell stays put meanwhile. */}
          <Suspense
            fallback={
              <div
                className="mx-auto grid w-full max-w-6xl gap-4 px-4 py-6 sm:px-6 lg:px-8"
                aria-busy="true"
              >
                <Skeleton className="h-8 w-56" />
                <Skeleton className="h-64 w-full" />
              </div>
            }
          >
            {children}
          </Suspense>
        </main>
      </div>

      <CommandMenu open={commandOpen} onOpenChange={setCommandOpen} />
      <CopilotPanel open={copilotOpen} onOpenChange={setCopilotOpen} />
    </div>
  );
}
