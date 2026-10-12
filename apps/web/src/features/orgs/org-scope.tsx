import { createContext, useContext, useEffect, useMemo } from 'react';
import { Outlet, useParams } from 'react-router-dom';

import { AppShell } from '@/components/layout/app-shell';
import { ErrorState } from '@/components/feedback';
import { Skeleton } from '@/components/ui/misc';
import { useMe } from '@/features/auth/api';
import { useOrg } from '@/features/orgs/api';
import type { Org, Role } from '@/lib/api/types';
import { useLiveEvents } from '@/lib/live-events';

export interface OrgScope {
  orgId: string;
  org: Org;
  roles: Role[];
  /** The treasury in the URL, else the last one opened, else the first. */
  treasuryId: string | undefined;
  /** `/o/:org` */
  base: string;
  /** `/o/:org/t/:t` (falls back to onboarding when there is no treasury). */
  tBase: string;
  can: (...roles: Role[]) => boolean;
  /** Resolves an API-relative link ("plans/p1", "approvals/r1") to a route. */
  resolve: (href: string) => string;
  live: boolean;
}

const OrgScopeContext = createContext<OrgScope | null>(null);

// eslint-disable-next-line react-refresh/only-export-components
export function useOrgScope(): OrgScope {
  const scope = useContext(OrgScopeContext);
  if (!scope) throw new Error('useOrgScope must be used under /o/:org');
  return scope;
}

/** Treasury-scoped routes call this: the wizard guarantees a treasury exists. */
// eslint-disable-next-line react-refresh/only-export-components
export function useTreasuryScope() {
  const scope = useOrgScope();
  const { t } = useParams();
  return { ...scope, treasuryId: t ?? scope.treasuryId ?? '' };
}

const lastTreasuryKey = (orgId: string) => `treasurypilot.treasury.${orgId}`;
const treasuryScoped =
  /^(dashboard|plans|payees|mandate|settings|borrow)(\/|$|\?)/;

export function OrgLayout() {
  const params = useParams();
  const orgId = params.org ?? '';
  const me = useMe();
  const orgQuery = useOrg(orgId);
  const { live } = useLiveEvents(orgQuery.data ? orgId : undefined);

  const org = orgQuery.data?.org;
  const remembered = useMemo(() => {
    try {
      return window.localStorage.getItem(lastTreasuryKey(orgId)) ?? undefined;
    } catch {
      return undefined;
    }
  }, [orgId]);
  const treasuryId =
    params.t ??
    org?.treasuries.find((item) => item.id === remembered)?.id ??
    org?.treasuries[0]?.id;

  useEffect(() => {
    if (!params.t) return;
    try {
      window.localStorage.setItem(lastTreasuryKey(orgId), params.t);
    } catch {
      /* preference only */
    }
  }, [orgId, params.t]);

  const scope = useMemo<OrgScope | null>(() => {
    if (!org) return null;
    const roles =
      me.data?.memberships.find((item) => item.orgId === orgId)?.roles ?? [];
    const base = `/o/${orgId}`;
    const tBase = treasuryId ? `${base}/t/${treasuryId}` : `${base}/onboarding`;
    return {
      orgId,
      org,
      roles,
      treasuryId,
      base,
      tBase,
      live,
      can: (...wanted) => wanted.some((role) => roles.includes(role)),
      resolve: (href) => {
        if (href.startsWith('/')) return href;
        if (href === 'dashboard') return tBase;
        return `${treasuryScoped.test(href) ? tBase : base}/${href}`;
      },
    };
  }, [live, me.data, org, orgId, treasuryId]);

  if (orgQuery.isError) {
    return (
      <div className="grid min-h-dvh place-items-center">
        <ErrorState
          error={orgQuery.error}
          title="This organization is not available"
          onRetry={() => void orgQuery.refetch()}
        />
      </div>
    );
  }
  if (!scope) {
    return (
      <div className="flex min-h-dvh" aria-busy="true">
        <div className="hidden w-60 border-r bg-surface p-4 lg:block">
          <Skeleton className="h-8 w-full" />
          <Skeleton className="mt-6 h-40 w-full" />
        </div>
        <div className="flex-1 p-8">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="mt-6 h-64 w-full" />
        </div>
      </div>
    );
  }
  return (
    <OrgScopeContext.Provider value={scope}>
      <AppShell>
        <Outlet />
      </AppShell>
    </OrgScopeContext.Provider>
  );
}
