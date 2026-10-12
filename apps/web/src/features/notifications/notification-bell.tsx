import {
  Bell,
  CheckCheck,
  ClipboardCheck,
  Info,
  PenLine,
  TriangleAlert,
  Workflow,
} from 'lucide-react';
import { useState } from 'react';
import { Drawer } from 'vaul';
import { useNavigate } from 'react-router-dom';

import { EmptyState, ErrorState, ListSkeleton } from '@/components/feedback';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/menus';
import {
  useMarkNotificationRead,
  useNotifications,
} from '@/features/operations/api';
import { useOrgScope } from '@/features/orgs/org-scope';
import type { Notification } from '@/lib/api/types';
import { formatRelative } from '@/lib/format';
import { t } from '@/lib/i18n';
import { useMediaQuery } from '@/lib/use-media-query';
import { cn } from '@/lib/utils';

const kindIcon = {
  approval: ClipboardCheck,
  governance: PenLine,
  execution: Workflow,
  review: TriangleAlert,
  system: Info,
} as const;

function groupByDay(items: Notification[]) {
  const today = new Date().toDateString();
  const groups = new Map<string, Notification[]>();
  for (const item of items) {
    const key =
      new Date(item.at).toDateString() === today ? t('Today') : t('Earlier');
    groups.set(key, [...(groups.get(key) ?? []), item]);
  }
  return [...groups.entries()];
}

function NotificationList({ onNavigate }: { onNavigate: () => void }) {
  const scope = useOrgScope();
  const navigate = useNavigate();
  const query = useNotifications(scope.orgId);
  const markRead = useMarkNotificationRead(scope.orgId);

  if (query.isPending) return <ListSkeleton rows={4} />;
  if (query.isError) {
    return (
      <ErrorState error={query.error} onRetry={() => void query.refetch()} />
    );
  }
  const items = query.data.items;
  if (items.length === 0) {
    return (
      <EmptyState
        icon={Bell}
        title={t('Nothing yet')}
        description={t(
          'Approvals to sign, governance transactions and execution results will appear here.',
        )}
      />
    );
  }
  const unread = items.filter((item) => !item.read).length;

  return (
    <div>
      <div className="flex items-center justify-between gap-2 border-b px-4 py-2.5">
        <p className="text-base font-semibold">
          {t('Notifications')}
          {unread > 0 && (
            <span className="ml-1.5 font-normal text-muted-foreground">
              {t('{{count}} unread', { count: unread })}
            </span>
          )}
        </p>
        <Button
          variant="ghost"
          size="sm"
          disabled={unread === 0}
          onClick={() => markRead.mutate('all')}
        >
          <CheckCheck aria-hidden="true" />
          {t('Mark all read')}
        </Button>
      </div>
      <div className="max-h-[60dvh] overflow-y-auto">
        {groupByDay(items).map(([day, group]) => (
          <section key={day} aria-label={day}>
            <p className="bg-surface-muted px-4 py-1 text-xs font-medium text-muted-foreground">
              {day}
            </p>
            <ul className="divide-y">
              {group.map((item) => {
                const Icon = kindIcon[item.kind];
                return (
                  <li key={item.id}>
                    <button
                      type="button"
                      className="flex w-full gap-3 px-4 py-3 text-left hover:bg-surface-muted"
                      onClick={() => {
                        if (!item.read) markRead.mutate(item.id);
                        onNavigate();
                        navigate(scope.resolve(item.href));
                      }}
                    >
                      <Icon
                        className="mt-0.5 size-4 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                      <span className="min-w-0 flex-1">
                        <span
                          className={cn(
                            'block text-base',
                            item.read ? 'text-muted-foreground' : 'font-medium',
                          )}
                        >
                          {item.title}
                        </span>
                        <span className="block text-sm text-muted-foreground">
                          {item.body}
                        </span>
                        <span className="mt-0.5 block text-xs text-subtle-foreground">
                          {formatRelative(item.at)}
                        </span>
                      </span>
                      {!item.read && (
                        <span
                          className="mt-1.5 size-2 shrink-0 rounded-full bg-primary"
                          aria-label={t('Unread')}
                        />
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

/** Bell with unread count: a popover on desktop, a bottom sheet at 390 px. */
export function NotificationBell() {
  const scope = useOrgScope();
  const [open, setOpen] = useState(false);
  const desktop = useMediaQuery('(min-width: 640px)');
  const unread =
    useNotifications(scope.orgId).data?.items.filter((item) => !item.read)
      .length ?? 0;

  const trigger = (
    <Button
      variant="ghost"
      size="icon"
      className="relative"
      aria-label={
        unread > 0
          ? t('Notifications, {{count}} unread', { count: unread })
          : t('Notifications')
      }
    >
      <Bell aria-hidden="true" />
      {unread > 0 && (
        <span className="num absolute right-1 top-1 grid min-w-4 place-items-center rounded-full bg-danger px-1 text-xs font-medium leading-4 text-white">
          {unread}
        </span>
      )}
    </Button>
  );

  if (desktop) {
    return (
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
        <PopoverContent align="end" className="w-96 overflow-hidden p-0">
          <NotificationList onNavigate={() => setOpen(false)} />
        </PopoverContent>
      </Popover>
    );
  }
  return (
    <Drawer.Root open={open} onOpenChange={setOpen}>
      <Drawer.Trigger asChild>{trigger}</Drawer.Trigger>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 z-50 bg-overlay/50" />
        <Drawer.Content
          aria-describedby={undefined}
          className="fixed inset-x-0 bottom-0 z-50 rounded-t-lg border-t bg-surface pb-[env(safe-area-inset-bottom)]"
        >
          <Drawer.Title className="sr-only">{t('Notifications')}</Drawer.Title>
          <div
            className="mx-auto my-2 h-1 w-10 rounded-full bg-border-strong"
            aria-hidden="true"
          />
          <NotificationList onNavigate={() => setOpen(false)} />
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
