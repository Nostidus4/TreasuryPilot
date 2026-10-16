import { useQuery } from '@tanstack/react-query';

import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api, isApiError } from '@/lib/api/http';
import { mockApiEnabled } from '@/lib/env';
import type {
  GovernanceStatus,
  GovernanceTx,
  Hex,
  MandateConfig,
  MandateDraft,
  MandateVersion,
  Payee,
  TxCall,
  TypedData,
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

/* ───────────── Governance ───────────── */

/** The governance transaction as the real API returns it (flat, Safe-oriented). */
interface ApiGovernanceTx {
  id: string;
  treasuryId: string;
  purpose: string;
  safeAddress: Hex;
  nonce: number;
  safeTxHash: Hex;
  decodedCalls: Array<{
    to: Hex;
    value: string;
    data: Hex;
    operation?: number;
  }>;
  humanSummary: string;
  typedData: TypedData;
  threshold: number;
  owners: Hex[];
  status: string;
  execTxHash: Hex | null;
  signatures: Array<{ owner: Hex; signature: Hex; at: string }>;
}

const governanceStatusMap: Record<string, GovernanceStatus> = {
  Collecting: 'AwaitingSignatures',
  Ready: 'ReadyToExecute',
  Submitted: 'Executing',
  Executed: 'Executed',
  Failed: 'Failed',
  Superseded: 'Superseded',
  Cancelled: 'Superseded',
};

const governancePurpose: Record<
  string,
  { kind: GovernanceTx['kind']; title: string }
> = {
  MODULE_SETUP: { kind: 'DEPLOY_MODULE', title: 'Deploy the treasury module' },
  MANDATE: { kind: 'CONFIGURE_MANDATE', title: 'Activate a mandate' },
  PAYEE_ADD: { kind: 'ADD_PAYEE', title: 'Register a payee' },
  PAYEE_DEACTIVATE: { kind: 'DEACTIVATE_PAYEE', title: 'Deactivate a payee' },
  EXCEPTION_GRANT: { kind: 'GRANT_EXCEPTION', title: 'Grant an exception' },
  EXCEPTION_REVOKE: { kind: 'GRANT_EXCEPTION', title: 'Revoke an exception' },
  RESUME: { kind: 'RESUME', title: 'Resume the treasury' },
  REVOKE: { kind: 'REVOKE', title: 'Revoke the treasury module' },
};

/** Adapt the API's flat governance transaction to the view the signing screens use. */
export function toGovernanceView(
  raw: ApiGovernanceTx | { governanceTx: GovernanceTx; typedData: TypedData },
): {
  governanceTx: GovernanceTx;
  typedData: TypedData;
} {
  // The mock API (src/mocks) already serves the view shape.
  if ('governanceTx' in raw) return raw;
  const purpose = governancePurpose[raw.purpose] ?? {
    kind: 'CONFIGURE_MANDATE' as const,
    title: raw.purpose,
  };
  return {
    typedData: raw.typedData,
    governanceTx: {
      id: raw.id,
      kind: purpose.kind,
      title: purpose.title,
      summary: raw.humanSummary,
      status: governanceStatusMap[raw.status] ?? 'Superseded',
      treasuryId: raw.treasuryId,
      safeAddress: raw.safeAddress,
      safeLabel: 'Treasury Safe',
      nonce: raw.nonce,
      threshold: raw.threshold,
      owners: raw.owners.map((address) => ({ address, name: address })),
      signatures: raw.signatures.map(({ owner, at }) => ({ owner, at })),
      calls: raw.decodedCalls.map((call) => ({
        to: call.to,
        toLabel: '',
        value: call.value,
        operation: call.operation === 1 ? 1 : 0,
        method: call.data.slice(0, 10),
        params: [],
        data: call.data,
      })),
      safeTxHash: raw.safeTxHash,
      txHash: raw.execTxHash ?? undefined,
    },
  };
}

/**
 * The API has no org-wide governance list yet, so the inbox is empty there; a transaction is
 * still reachable by id.
 */
export const useGovernanceTxs = (orgId: string, status?: GovernanceStatus) =>
  useQuery<{ items: GovernanceTx[] }>({
    queryKey: ['org', orgId, 'governance', 'list', status ?? null],
    queryFn: async ({ signal }) => {
      try {
        return await api.get<{ items: GovernanceTx[] }>(
          `/orgs/${orgId}/governance-txs`,
          { query: { status }, signal },
        );
      } catch (error) {
        if (isApiError(error) && [404, 405].includes(error.status))
          return { items: [] };
        throw error;
      }
    },
  });

export const useGovernanceTx = (orgId: string, id: string | undefined) =>
  useQuery({
    queryKey: ['org', orgId, 'governance', 'detail', id],
    queryFn: async ({ signal }) =>
      toGovernanceView(
        await api.get<
          ApiGovernanceTx | { governanceTx: GovernanceTx; typedData: TypedData }
        >(`/orgs/${orgId}/governance-txs/${id}`, { signal }),
      ),
    enabled: Boolean(id),
    // Each read re-checks the receipt, so poll while the transaction is in flight.
    refetchInterval: (query) =>
      query.state.data?.governanceTx.status === 'Executing' ? 3000 : false,
  });

export const useSubmitGovernanceSignature = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; signature: Hex }) =>
    api.post<ApiGovernanceTx>(
      `/orgs/${orgId}/governance-txs/${input.id}/signatures`,
      { signature: input.signature },
      { idempotent: true },
    ),
  );

export const fetchExecCall = (orgId: string, id: string) =>
  api.get<TxCall>(`/orgs/${orgId}/governance-txs/${id}/exec-call`);

export const useReportGovernanceSubmitted = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; txHash: Hex }) =>
    api.post<ApiGovernanceTx>(
      `/orgs/${orgId}/governance-txs/${input.id}/submitted`,
      mockApiEnabled
        ? { txHash: input.txHash }
        : { transactionHash: input.txHash },
    ),
  );

export const useCancelGovernanceTx = (orgId: string) =>
  useOrgMutation(orgId, (id: string) =>
    api.post<{ status: GovernanceStatus }>(
      `/orgs/${orgId}/governance-txs/${id}/cancel`,
    ),
  );
