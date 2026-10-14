import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type {
  BorrowProposal,
  Coverage,
  FeePolicy,
  FeeSetting,
  Forecast,
  GovernanceTx,
  Hex,
  Treasury,
  TreasuryState,
  WalletRole,
} from '@/lib/api/types';

const base = (orgId: string, treasuryId: string) =>
  `/orgs/${orgId}/treasuries/${treasuryId}`;

export const useTreasury = (orgId: string, treasuryId: string | undefined) =>
  useOrgQuery<TreasuryState>(
    orgId,
    'treasury',
    [treasuryId],
    `/treasuries/${treasuryId}`,
    { enabled: Boolean(treasuryId) },
  );

export const useForecast = (orgId: string, treasuryId: string) =>
  useOrgQuery<Forecast>(
    orgId,
    'treasury',
    [treasuryId, 'forecast'],
    `/treasuries/${treasuryId}/forecast`,
  );

export const useBorrowProposal = (
  orgId: string,
  treasuryId: string,
  id: string,
) =>
  useOrgQuery<BorrowProposal>(
    orgId,
    'treasury',
    [treasuryId, 'borrow', id],
    `/treasuries/${treasuryId}/borrow-proposals/${id}`,
  );

export const useFeePolicy = (orgId: string, treasuryId: string) =>
  useOrgQuery<FeePolicy>(
    orgId,
    'treasury',
    [treasuryId, 'fees'],
    `/treasuries/${treasuryId}/fee-policy`,
  );

export const useAcceptFeePolicy = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (input: { preset?: string }) =>
    api.post<{ active: FeeSetting }>(
      `${base(orgId, treasuryId)}/fee-policy/accept`,
      input,
    ),
  );

export const usePauseTreasury = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (reason: string) =>
    api.post<{
      backendPaused: boolean;
      onchain: string;
      sentinelTxHash?: Hex;
    }>(`${base(orgId, treasuryId)}/pause`, { reason }, { idempotent: true }),
  );

export const useResumeTx = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, () =>
    api.post<{ governanceTx: GovernanceTx }>(
      `${base(orgId, treasuryId)}/resume-tx`,
    ),
  );

export interface TreasuryInput {
  name: string;
  chainId: number;
  assetId: string;
  wallets: Array<{ role: WalletRole; safeAddress: string; label: string }>;
}

export const useCreateTreasury = (orgId: string) =>
  useOrgMutation(orgId, (input: TreasuryInput) =>
    api.post<{ treasury: Treasury }>(`/orgs/${orgId}/treasuries`, input),
  );

export const useSafeDeploymentTx = (orgId: string) =>
  useOrgMutation(
    orgId,
    (input: { chainId: number; owners: string[]; threshold: number }) =>
      api.post<{
        chainId: number;
        transaction: { to: Hex; data: Hex; value: string };
      }>(`/orgs/${orgId}/safes/deploy-tx`, input),
  );

export const useDeployModuleTx = (orgId: string) =>
  useOrgMutation(orgId, (treasuryId: string) =>
    api.post<{ governanceTx: GovernanceTx }>(
      `${base(orgId, treasuryId)}/module/deploy-tx`,
    ),
  );

export const useRefreshCoverage = (orgId: string) =>
  useOrgMutation(orgId, (treasuryId: string) =>
    api.post<{ coverage: Coverage }>(
      `${base(orgId, treasuryId)}/coverage/refresh`,
    ),
  );

export const useAcknowledgeCoverage = (orgId: string) =>
  useOrgMutation(orgId, (input: { treasuryId: string; reason: string }) =>
    api.post<{ coverage: Coverage }>(
      `${base(orgId, input.treasuryId)}/coverage/acknowledge`,
      { reason: input.reason },
    ),
  );

export const useSetGuardian = (orgId: string) =>
  useOrgMutation(orgId, (input: { treasuryId: string; safeAddress: string }) =>
    api.post<{ treasury: Treasury }>(
      `${base(orgId, input.treasuryId)}/guardian`,
      { safeAddress: input.safeAddress },
    ),
  );
