import { useQuery } from '@tanstack/react-query';

import {
  fromDraftResponse,
  fromMandateView,
  type MandateDraftWire,
  type MandateView,
} from '@/features/mandate/wire';
import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type {
  GovernanceTx,
  MandateConfig,
  Payee,
  Vendor,
} from '@/lib/api/types';
import type { components } from '@/lib/api/schema';

const treasuryBase = (orgId: string, treasuryId: string) =>
  `/orgs/${orgId}/treasuries/${treasuryId}`;

/* ───────────── Mandate ───────────── */

export const useMandates = (orgId: string, treasuryId: string) =>
  useQuery({
    queryKey: ['org', orgId, 'mandates', treasuryId, null],
    queryFn: async ({ signal }) => {
      const { items } = await api.get<{ items: MandateView[] }>(
        `/orgs/${orgId}/treasuries/${treasuryId}/mandates`,
        { signal },
      );
      return { items: items.map(fromMandateView) };
    },
  });

/** Owner-only and step-up gated: a 403 `STEP_UP_REQUIRED` means ask for the code and retry. */
export const useSaveMandateDraft = (
  orgId: string,
  treasuryId: string,
  asset: { decimals: number; symbol: string },
) =>
  useOrgMutation(orgId, async (config: MandateConfig) =>
    fromDraftResponse(
      await api.post<MandateDraftWire>(
        `${treasuryBase(orgId, treasuryId)}/mandates`,
        config,
      ),
      asset,
    ),
  );

/** Creates the Safe transaction for a draft (by id); the response is the governance tx. */
export const useMandateActivationTx = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (mandateId: string) =>
    api.post<{ id: string }>(
      `${treasuryBase(orgId, treasuryId)}/mandates/${mandateId}/governance-tx`,
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
  useOrgMutation(
    orgId,
    (input: components['schemas']['PayeeCreate']) =>
      api.post<components['schemas']['PayeeResponse']>(
        `${treasuryBase(orgId, treasuryId)}/payees`,
        input,
      ),
    // A screening hit is a 422 after the API stored the payee as ScreeningFailed.
    'payees',
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
    'payees',
  );
