import { recoverMessageAddress } from 'viem';

import type {
  ChecklistItem,
  Hex,
  Me,
  Member,
  Org,
  OrgDetail,
  Role,
} from '@/lib/api/types';
import { ADDR, CHAINS, db, demoUser, membersOf, setSession } from '@/mocks/db';

import { fail, find, isLinked, isoNow, route, sameAddress } from './core';

const SIGNER_ROLES: Role[] = ['OWN', 'APR', 'GRD'];

function orgsOf(userId: string): Org[] {
  return db.orgs.filter((org) =>
    membersOf(org.id).some((member) => member.userId === userId),
  );
}

export function requireOrg(orgId: string): Org {
  const org = db.orgs.find((item) => item.id === orgId);
  // 404 rather than 403: no existence leak (API_SPEC §0).
  if (!org || !orgsOf(db.session!.id).includes(org)) {
    fail(404, 'NOT_FOUND', 'Organization was not found.');
  }
  return org;
}

function checklist(org: Org): ChecklistItem[] {
  const treasuryId = org.treasuries[0]?.id;
  const state = treasuryId ? db.treasuries[treasuryId] : undefined;
  const base = `/o/${org.id}`;
  return [
    {
      key: 'wallet',
      title: 'Link your wallet',
      description:
        'Approvals and governance transactions are signed with your own wallet.',
      done: db.linkedWallets.length > 0,
      href: '/me/wallets',
    },
    {
      key: 'treasury',
      title: 'Set up a treasury',
      description:
        'Connect your Safes, enable the TreasuryPilot module and check coverage.',
      done: Boolean(state && state.treasury.status !== 'Setup'),
      href: `${base}/treasuries/new`,
    },
    {
      key: 'mandate',
      title: 'Activate a mandate',
      description:
        'Limits, buffers and approvers the agent can never exceed, enforced on-chain.',
      done: state?.mandate?.status === 'Active',
      href: treasuryId
        ? `${base}/t/${treasuryId}/mandate`
        : `${base}/treasuries/new`,
    },
    {
      key: 'payee',
      title: 'Register your first payee',
      description:
        'Only registered payees past their cooling period can be paid.',
      done: db.payees.some(
        (payee) => payee.treasuryId === treasuryId && payee.status === 'Active',
      ),
      href: treasuryId
        ? `${base}/t/${treasuryId}/payees`
        : `${base}/treasuries/new`,
    },
    {
      key: 'approver',
      title: 'Invite a second approver',
      description:
        'The person who creates a request cannot approve it (maker-checker).',
      done:
        org.soloMode ||
        membersOf(org.id).filter((member) => member.roles.includes('APR'))
          .length > 1,
      href: `${base}/members`,
    },
  ];
}

export const identityHandlers = [
  route<{ email?: string }>(
    'post',
    '/auth/magic-link',
    ({ body }) => {
      const email = body.email?.trim().toLowerCase() ?? '';
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        fail(422, 'EMAIL_INVALID', 'Enter a valid work email address.');
      }
      if (email.startsWith('ratelimit')) {
        fail(
          429,
          'RATE_LIMITED',
          'Too many sign-in links requested. Try again in a minute.',
        );
      }
    },
    { public: true, status: 202 },
  ),

  route<{ token?: string }>(
    'post',
    '/auth/magic-link/verify',
    ({ body }) => {
      const token = body.token ?? '';
      if (token === 'expired') {
        fail(
          410,
          'TOKEN_EXPIRED',
          'This sign-in link has expired. Request a new one.',
        );
      }
      if (!token.startsWith('mock.')) {
        fail(400, 'TOKEN_INVALID', 'This sign-in link is not valid.');
      }
      const email = decodeURIComponent(token.slice(5));
      const user =
        email === demoUser.email
          ? demoUser
          : email === 'an@northwind.test'
            ? { id: 'usr_an', email, name: 'An Nguyen' }
            : {
                id: `usr_${email.replace(/[^a-z0-9]/g, '_')}`,
                email,
                name: email
                  .split('@')[0]
                  .split(/[._-]/)
                  .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
                  .join(' '),
              };
      setSession(user);
      return { user };
    },
    { public: true },
  ),

  route('post', '/auth/logout', () => setSession(null)),

  route('get', '/me', (): Me => {
    const user = db.session!;
    return {
      user,
      memberships: orgsOf(user.id).map((org) => ({
        orgId: org.id,
        orgName: org.name,
        roles: membersOf(org.id).find((member) => member.userId === user.id)!
          .roles,
      })),
      wallets: db.linkedWallets,
    };
  }),

  route('get', '/auth/siwe/nonce', () => ({
    nonce: Math.random().toString(36).slice(2, 12),
    expiresAt: new Date(Date.now() + 5 * 60_000).toISOString(),
  })),

  route<{ message: string; signature: Hex }>(
    'post',
    '/me/wallets',
    async ({ body }) => {
      let address: Hex;
      try {
        address = await recoverMessageAddress({
          message: body.message,
          signature: body.signature,
        });
      } catch {
        fail(400, 'SIWE_INVALID', 'The signature could not be verified.');
      }
      if (!body.message.toLowerCase().includes(address.toLowerCase())) {
        fail(
          400,
          'SIWE_INVALID',
          'The signature does not match the address in the message.',
        );
      }
      if (sameAddress(address, ADDR.an)) {
        fail(
          409,
          'ADDRESS_LINKED_ELSEWHERE',
          'This wallet is already linked to another account.',
        );
      }
      if (!isLinked(address)) {
        db.linkedWallets.push({ address, linkedAt: isoNow() });
      }
      const me = db.members.find((member) => member.userId === db.session!.id);
      if (me && !me.wallet) me.wallet = address;
      return { address };
    },
    { status: 201 },
  ),

  route('delete', '/me/wallets/:address', ({ params }) => {
    const holdsSignerRole = orgsOf(db.session!.id).some((org) =>
      membersOf(org.id)
        .find((member) => member.userId === db.session!.id)
        ?.roles.some((role) => SIGNER_ROLES.includes(role)),
    );
    if (db.linkedWallets.length === 1 && holdsSignerRole) {
      fail(
        409,
        'SIGNER_ROLE_REQUIRES_WALLET',
        'You hold a signing role (Owner, Approver or Guardian). Link another wallet before removing this one.',
      );
    }
    db.linkedWallets = db.linkedWallets.filter(
      (wallet) => !sameAddress(wallet.address, params.address),
    );
  }),

  route('get', '/chains', () => ({ chains: CHAINS })),

  route<{
    name?: string;
    legalName?: string;
    country?: string;
    displayTz?: string;
  }>(
    'post',
    '/orgs',
    ({ body }) => {
      const name = body.name?.trim();
      if (!name) {
        fail(422, 'VALIDATION', 'Organization name is required.', [
          { field: 'name', message: 'Enter the organization name.' },
        ]);
      }
      const org: Org = {
        id: `org_${name.toLowerCase().replace(/[^a-z0-9]+/g, '_')}_${db.orgs.length}`,
        name,
        legalName: body.legalName,
        country: body.country ?? 'VN',
        displayTz: body.displayTz ?? 'Asia/Ho_Chi_Minh',
        soloMode: false,
        autoMatch: true,
        treasuries: [],
      };
      db.orgs.push(org);
      const user = db.session!;
      // The spec makes the creator OrgAdmin; the mock also grants Owner so the
      // setup wizard is reachable without a second account.
      db.orgMembers[org.id] = [
        {
          userId: user.id,
          name: user.name,
          email: user.email,
          roles: ['ADM', 'OWN', 'OPR', 'APR', 'FIN'],
          wallet: db.linkedWallets[0]?.address,
          status: 'Active',
          joinedAt: isoNow(),
        },
      ];
      return { org };
    },
    { status: 201 },
  ),

  route('get', '/orgs/:orgId', ({ params }): OrgDetail => {
    const org = requireOrg(params.orgId);
    return { org, checklist: checklist(org) };
  }),

  route<{ soloMode?: boolean; autoMatch?: boolean }>(
    'patch',
    '/orgs/:orgId/settings',
    ({ params, body }) => {
      const org = requireOrg(params.orgId);
      if (body.soloMode !== undefined) org.soloMode = body.soloMode;
      if (body.autoMatch !== undefined) org.autoMatch = body.autoMatch;
      return { org };
    },
  ),

  route('get', '/orgs/:orgId/members', ({ params }) => {
    requireOrg(params.orgId);
    return { items: membersOf(params.orgId) };
  }),

  route<{ email?: string; roles?: Role[] }>(
    'post',
    '/orgs/:orgId/invites',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const email = body.email?.trim().toLowerCase() ?? '';
      const members = membersOf(params.orgId);
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        fail(422, 'EMAIL_INVALID', 'Enter a valid email address.');
      }
      if (!body.roles?.length) {
        fail(422, 'VALIDATION', 'Choose at least one role.');
      }
      if (members.some((member) => member.email === email)) {
        fail(
          409,
          'ALREADY_MEMBER',
          `${email} is already a member or has a pending invite.`,
        );
      }
      const member: Member = {
        userId: `usr_inv_${members.length}`,
        name: email.split('@')[0],
        email,
        roles: body.roles,
        status: 'Invited',
        joinedAt: isoNow(),
      };
      members.push(member);
      return { invite: member };
    },
    { status: 201 },
  ),

  route<{ roles: Role[] }>(
    'patch',
    '/orgs/:orgId/members/:userId',
    ({ params, body }) => {
      requireOrg(params.orgId);
      const members = membersOf(params.orgId);
      const member = find(
        members,
        (item) => item.userId === params.userId,
        'Member',
      );
      const others = members.filter(
        (item) => item !== member && item.status === 'Active',
      );
      for (const [role, code] of [
        ['ADM', 'LAST_ADMIN'],
        ['OWN', 'LAST_OWNER'],
      ] as const) {
        if (
          member.roles.includes(role) &&
          !body.roles.includes(role) &&
          !others.some((item) => item.roles.includes(role))
        ) {
          fail(
            409,
            code,
            `The organization must keep at least one ${role === 'ADM' ? 'admin' : 'owner'}.`,
          );
        }
      }
      member.roles = body.roles;
      return { membership: member };
    },
  ),

  route('delete', '/orgs/:orgId/members/:userId', ({ params }) => {
    requireOrg(params.orgId);
    const members = membersOf(params.orgId);
    const member = find(
      members,
      (item) => item.userId === params.userId,
      'Member',
    );
    if (
      member.roles.includes('ADM') &&
      !members.some((item) => item !== member && item.roles.includes('ADM'))
    ) {
      fail(409, 'LAST_ADMIN', 'The organization must keep at least one admin.');
    }
    members.splice(members.indexOf(member), 1);
  }),
];
