import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { meKey } from '@/features/auth/api';
import { useOrgMutation } from '@/lib/api/hooks';
import { api, isApiError } from '@/lib/api/http';
import { fromApiRoles, toApiRole } from '@/lib/api/roles';
import type { components } from '@/lib/api/schema';
import type {
  ChecklistItem,
  Member,
  Org,
  OrgDetail,
  Role,
  TreasurySummary,
} from '@/lib/api/types';

type Schemas = components['schemas'];
type ApiOrg = Schemas['OrganizationView'];

const toOrg = (org: ApiOrg, treasuries: TreasurySummary[]): Org => ({
  ...org,
  legalName: org.legalName ?? undefined,
  country: org.country ?? '',
  // The API has no treasury name; chain and asset identify it within an org.
  treasuries: treasuries.map((item) => ({
    id: item.id,
    name: `${item.chainName} · ${item.assetSymbol}`,
  })),
});

function checklistItems(
  org: Org,
  checklist: Schemas['OrganizationChecklist'],
): ChecklistItem[] {
  const base = `/o/${org.id}`;
  const treasuryId = org.treasuries[0]?.id;
  return [
    {
      key: 'wallet',
      title: 'Link your wallet',
      description:
        'Approvals and governance transactions are signed with your own wallet.',
      done: checklist.walletLinked,
      href: '/me/wallets',
    },
    {
      key: 'treasury',
      title: 'Set up a treasury',
      description: 'Connect your Safes and check coverage.',
      done: checklist.treasuryCreated,
      href: `${base}/treasuries/new`,
    },
    {
      key: 'module',
      title: 'Enable the TreasuryPilot module',
      description:
        'Limits, buffers and approvers the agent can never exceed, enforced on-chain.',
      done: checklist.moduleEnabled,
      href: treasuryId
        ? `${base}/t/${treasuryId}/mandate`
        : `${base}/treasuries/new`,
    },
    {
      key: 'approver',
      title: 'Invite a second member',
      description:
        'The person who creates a request cannot approve it (maker-checker).',
      done: org.soloMode || checklist.memberCount > 1,
      href: `${base}/members`,
    },
  ];
}

export const useOrg = (orgId: string) =>
  useQuery({
    queryKey: ['org', orgId, 'org'],
    queryFn: async ({ signal }): Promise<OrgDetail> => {
      const [detail, treasuries] = await Promise.all([
        api.get<Schemas['OrganizationDetailsResponse']>(`/orgs/${orgId}`, {
          signal,
        }),
        api.get<{ items: TreasurySummary[] }>(`/orgs/${orgId}/treasuries`, {
          signal,
        }),
      ]);
      const org = toOrg(detail.org, treasuries.items);
      return { org, checklist: checklistItems(org, detail.checklist) };
    },
  });

export function useCreateOrg() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: {
      name: string;
      legalName?: string;
      country: string;
      displayTz: string;
    }) => api.post<{ org: ApiOrg }>('/orgs', input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

export const useUpdateOrgSettings = (orgId: string) =>
  useOrgMutation(orgId, (input: { soloMode?: boolean; autoMatch?: boolean }) =>
    api.patch<{ org: ApiOrg }>(`/orgs/${orgId}/settings`, input),
  );

const toMember = (member: Schemas['MemberView']): Member => ({
  userId: member.userId,
  name: member.email,
  email: member.email,
  roles: fromApiRoles(member.roles),
  status: 'Active',
});

const toInvite = (invite: Schemas['InviteView']): Member => ({
  userId: invite.id,
  name: invite.email,
  email: invite.email,
  roles: fromApiRoles(invite.roles),
  status: 'Invited',
});

/** Members plus pending invites; only admins may list invites, so others see members only. */
export const useMembers = (orgId: string) =>
  useQuery({
    queryKey: ['org', orgId, 'members'],
    queryFn: async ({ signal }): Promise<{ items: Member[] }> => {
      const [members, invites] = await Promise.all([
        api.get<Schemas['MembersResponse']>(`/orgs/${orgId}/members`, {
          signal,
        }),
        api
          .get<Schemas['InvitesResponse']>(`/orgs/${orgId}/invites`, { signal })
          .catch((error: unknown) => {
            if (isApiError(error) && error.status === 403)
              return { invites: [] };
            throw error;
          }),
      ]);
      return {
        items: [
          ...members.items.map(toMember),
          ...invites.invites.map(toInvite),
        ],
      };
    },
  });

export const useInviteMember = (orgId: string) =>
  useOrgMutation(orgId, (input: { email: string; roles: Role[] }) =>
    api.post<{ invite: Schemas['InviteView'] }>(`/orgs/${orgId}/invites`, {
      email: input.email,
      roles: input.roles.map(toApiRole),
    }),
  );

export const useUpdateMemberRoles = (orgId: string) =>
  useOrgMutation(orgId, (input: { userId: string; roles: Role[] }) =>
    api.patch<unknown>(`/orgs/${orgId}/members/${input.userId}`, {
      roles: input.roles.map(toApiRole),
    }),
  );

/** Removes a member, or revokes a pending invite (whose `userId` is the invite id). */
export const useRemoveMember = (orgId: string) =>
  useOrgMutation(orgId, (member: Member) =>
    api.delete<void>(
      member.status === 'Invited'
        ? `/orgs/${orgId}/invites/${member.userId}`
        : `/orgs/${orgId}/members/${member.userId}`,
    ),
  );
