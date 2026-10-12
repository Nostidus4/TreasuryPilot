import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
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
} from '@/lib/api/types';

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

export const useProposePayee = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (input: {
      vendorId?: string;
      vendorName?: string;
      label: string;
      address: string;
    }) =>
      api.post<{ payee: Payee }>(
        `${treasuryBase(orgId, treasuryId)}/payees`,
        input,
      ),
  );

export const useVerifyPayeeOob = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (input: { id: string; method: string; note: string }) =>
    api.post<{ payee: Payee }>(
      `${treasuryBase(orgId, treasuryId)}/payees/${input.id}/verify-oob`,
      { method: input.method, note: input.note },
    ),
  );

export const usePayeeTx = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (input: { id: string; kind: 'registration' | 'deactivation' }) =>
      api.post<{ governanceTx: GovernanceTx }>(
        `${treasuryBase(orgId, treasuryId)}/payees/${input.id}/${input.kind}-tx`,
      ),
  );

/* ───────────── Governance ───────────── */

export const useGovernanceTxs = (orgId: string, status?: GovernanceStatus) =>
  useOrgQuery<{ items: GovernanceTx[] }>(
    orgId,
    'governance',
    ['list'],
    '/governance-txs',
    { query: { status } },
  );

export const useGovernanceTx = (orgId: string, id: string | undefined) =>
  useOrgQuery<{ governanceTx: GovernanceTx; typedData: TypedData }>(
    orgId,
    'governance',
    ['detail', id],
    `/governance-txs/${id}`,
    { enabled: Boolean(id) },
  );

export const useSubmitGovernanceSignature = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; signature: Hex }) =>
    api.post<{ status: GovernanceStatus }>(
      `/orgs/${orgId}/governance-txs/${input.id}/signatures`,
      { signature: input.signature },
      { idempotent: true },
    ),
  );

export const fetchExecCall = (orgId: string, id: string) =>
  api.get<TxCall>(`/orgs/${orgId}/governance-txs/${id}/exec-call`);

export const useReportGovernanceSubmitted = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; txHash: Hex }) =>
    api.post<{ status: GovernanceStatus }>(
      `/orgs/${orgId}/governance-txs/${input.id}/submitted`,
      { txHash: input.txHash },
    ),
  );

export const useCancelGovernanceTx = (orgId: string) =>
  useOrgMutation(orgId, (id: string) =>
    api.post<{ status: GovernanceStatus }>(
      `/orgs/${orgId}/governance-txs/${id}/cancel`,
    ),
  );
