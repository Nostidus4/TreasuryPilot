import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type {
  GovernanceTx,
  MandateConfig,
  MandateDraft,
  MandateVersion,
  Payee,
  Vendor,
} from '@/lib/api/types';
import type { components } from '@/lib/api/schema';

const treasuryBase = (orgId: string, treasuryId: string) =>
  `/orgs/${orgId}/treasuries/${treasuryId}`;

/* ───────────── Mandate ───────────── */

export const useMandates = (orgId: string, treasuryId: string) =>
  useOrgQuery<{ items: MandateVersion[] }>(
    orgId,
    'mandates',
    [treasuryId],
    `/treasuries/${treasuryId}/mandates`,
  );

export const useSaveMandateDraft = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (config: MandateConfig) =>
    api.post<MandateDraft>(
      `${treasuryBase(orgId, treasuryId)}/mandates`,
      config,
    ),
  );

export const useMandateActivationTx = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (version: number) =>
    api.post<{ governanceTx: GovernanceTx }>(
      `${treasuryBase(orgId, treasuryId)}/mandates/${version}/activation-tx`,
    ),
  );

/* ───────────── Payees ───────────── */

export const usePayees = (orgId: string, treasuryId: string) =>
  useOrgQuery<{ items: Payee[] }>(
    orgId,
    'payees',
    [treasuryId],
    `/treasuries/${treasuryId}/payees`,
  );

export const useCreateVendor = (orgId: string) =>
  useOrgMutation(orgId, (name: string) =>
    api.post<{ vendor: Vendor }>(`/orgs/${orgId}/vendors`, { name }),
  );

export const useProposePayee = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (input: components['schemas']['PayeeCreate']) =>
    api.post<components['schemas']['PayeeResponse']>(
      `${treasuryBase(orgId, treasuryId)}/payees`,
      input,
    ),
  );

export const useVerifyPayeeOob = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (input: { id: string } & components['schemas']['OobVerification']) =>
      api.post<components['schemas']['PayeeResponse']>(
        `${treasuryBase(orgId, treasuryId)}/payees/${input.id}/verify-oob`,
        { method: input.method, note: input.note },
      ),
  );

export const usePayeeTx = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (input: {
      id: string;
      kind: 'registration' | 'deactivation';
      reason?: string;
    }) =>
      api.post<{ governanceTx: GovernanceTx }>(
        `${treasuryBase(orgId, treasuryId)}/payees/${input.id}/${input.kind}-tx`,
        input.kind === 'deactivation' ? { reason: input.reason } : undefined,
      ),
  );

/** Owner-only: deactivates the old address and starts a new payee's cooling. */
export const useReplacePayeeAddress = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (
      input: {
        id: string;
      } & components['schemas']['ReplacePayeeAddressRequest'],
    ) =>
      api.post<{ payee: Payee; deactivationGovernanceTx: GovernanceTx }>(
        `${treasuryBase(orgId, treasuryId)}/payees/${input.id}/replace-address`,
        { address: input.address, reason: input.reason },
      ),
  );
