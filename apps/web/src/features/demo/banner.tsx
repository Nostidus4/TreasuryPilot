import { Check, ChevronsUpDown, FlaskConical } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from '@/components/ui/menus';
import { t } from '@/lib/i18n';

import { useDemoSync, useScenario, useSwitchRole } from './api';
import { roleNames, utcSeconds } from './format';
import type { DemoRole } from './types';

/** Height of the banner; the shell pushes its own chrome down by this much. */
export const DEMO_BANNER_HEIGHT = '2.25rem';

/**
 * Always on screen in demo mode: the simulation label, the scenario clock and who is acting.
 * The role switcher is the only control in the recorded window; Director controls live in
 * their own window.
 */
export function DemoBanner() {
  useDemoSync();
  const scenario = useScenario();
  const switchRole = useSwitchRole();
  const state = scenario.data?.state;
  const role = state?.role ?? 'FINANCE';
  return (
    <div
      data-testid="demo-banner"
      style={{ height: DEMO_BANNER_HEIGHT }}
      className="fixed inset-x-0 top-0 z-[70] flex items-center gap-3 border-b border-warning-border bg-warning-muted px-3 text-sm text-warning-foreground sm:px-6"
    >
      <FlaskConical className="size-4 shrink-0" aria-hidden="true" />
      <span className="font-semibold tracking-wide">
        {t('SIMULATION / SYNTHETIC DATA')}
      </span>
      <span className="hidden text-warning-foreground/80 sm:inline">
        {t('Scenario time')}{' '}
        <span className="num font-medium" data-testid="demo-clock">
          {state ? utcSeconds(state.clock) : '…'}
        </span>
      </span>
      <div className="ml-auto flex items-center gap-2">
        <span className="hidden md:inline">
          {t('Role')}{' '}
          <Badge tone="outline" data-testid="demo-role">
            {roleNames[role].name} · {roleNames[role].title}
          </Badge>
        </span>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button size="sm" variant="secondary" data-testid="demo-role-menu">
              {t('Demo role')}: {roleNames[role].name}
              <ChevronsUpDown aria-hidden="true" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="z-[80] w-56">
            <DropdownMenuLabel>{t('Demo role')}</DropdownMenuLabel>
            {(Object.keys(roleNames) as DemoRole[]).map((item) => (
              <DropdownMenuItem
                key={item}
                disabled={switchRole.isPending}
                onSelect={() => switchRole.mutate(item)}
              >
                <span className="flex-1">
                  {roleNames[item].name} · {roleNames[item].title}
                </span>
                {item === role && <Check aria-hidden="true" />}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
