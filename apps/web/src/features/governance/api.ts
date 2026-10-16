import { useQuery } from '@tanstack/react-query';

import { useOrgMutation } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type { Hex, TxCall } from '@/lib/api/types';

import { toGovernanceTx, toTypedData, type GovernanceTxWire } from './wire';

export const useGovernanceTxs = (orgId: string) =>
  useQuery({
    queryKey: ['org', orgId, 'governance', 'list'],
    queryFn: ({ signal }) =>
      api.get<{ items: GovernanceTxWire[] }>(`/orgs/${orgId}/governance-txs`, {
        signal,
      }),
    select: ({ items }) => ({ items: items.map(toGovernanceTx) }),
  });

export const useGovernanceTx = (orgId: string, id: string | undefined) =>
  useQuery({
    queryKey: ['org', orgId, 'governance', 'detail', id],
    queryFn: ({ signal }) =>
      api.get<GovernanceTxWire>(`/orgs/${orgId}/governance-txs/${id}`, {
        signal,
      }),
    enabled: Boolean(id),
    select: (wire) => ({
      governanceTx: toGovernanceTx(wire),
      typedData: toTypedData(wire),
    }),
  });

export const useSubmitGovernanceSignature = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; signature: Hex }) =>
    api.post<GovernanceTxWire>(
      `/orgs/${orgId}/governance-txs/${input.id}/signatures`,
      { signature: input.signature },
      { idempotent: true },
    ),
  );

export const fetchExecCall = (orgId: string, id: string) =>
  api.get<TxCall>(`/orgs/${orgId}/governance-txs/${id}/exec-call`);

export const useReportGovernanceSubmitted = (orgId: string) =>
  useOrgMutation(orgId, (input: { id: string; txHash: Hex }) =>
    api.post<GovernanceTxWire>(
      `/orgs/${orgId}/governance-txs/${input.id}/submitted`,
      { transactionHash: input.txHash },
    ),
  );
