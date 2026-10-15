import type { Role } from '@/lib/api/types';

/** The API speaks role names (OrganizationRole); the web keeps the API_SPEC short codes. */
const API_ROLE: Record<Role, string> = {
  OWN: 'Owner',
  APR: 'Approver',
  OPR: 'Operator',
  FIN: 'Finance',
  GRD: 'Guardian',
  ADM: 'OrgAdmin',
  AUD: 'Auditor',
};

const WEB_ROLE = Object.fromEntries(
  Object.entries(API_ROLE).map(([code, name]) => [name, code as Role]),
);

export const toApiRole = (role: Role) => API_ROLE[role];

/** Names without an org-level code (PlatformAdmin) are dropped. */
export const fromApiRoles = (roles: readonly string[]): Role[] =>
  roles.flatMap((name) => WEB_ROLE[name] ?? []);
