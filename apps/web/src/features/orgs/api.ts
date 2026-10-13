import { useMutation, useQueryClient } from '@tanstack/react-query';

import { meKey } from '@/features/auth/api';
import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type { Member, Org, OrgDetail, Role } from '@/lib/api/types';

export const useOrg = (orgId: string) =>
  useOrgQuery<OrgDetail>(orgId, 'org', [], '');

export function useCreateOrg() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      name: string;
      legalName?: string;
      country: string;
      displayTz: string;
    }) => api.post<{ org: Org }>('/orgs', input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

export const useUpdateOrgSettings = (orgId: string) =>
  useOrgMutation(orgId, (input: { soloMode?: boolean; autoMatch?: boolean }) =>
    api.patch<{ org: Org }>(`/orgs/${orgId}/settings`, input),
  );

export const useMembers = (orgId: string) =>
  useOrgQuery<{ items: Member[] }>(orgId, 'members', [], '/members');

export const useInviteMember = (orgId: string) =>
  useOrgMutation(orgId, (input: { email: string; roles: Role[] }) =>
    api.post<{ invite: Member }>(`/orgs/${orgId}/invites`, input),
  );

export const useUpdateMemberRoles = (orgId: string) =>
  useOrgMutation(orgId, (input: { userId: string; roles: Role[] }) =>
    api.patch<{ membership: Member }>(
      `/orgs/${orgId}/members/${input.userId}`,
      { roles: input.roles },
    ),
  );

export const useRemoveMember = (orgId: string) =>
  useOrgMutation(orgId, (userId: string) =>
    api.delete<void>(`/orgs/${orgId}/members/${userId}`),
  );
