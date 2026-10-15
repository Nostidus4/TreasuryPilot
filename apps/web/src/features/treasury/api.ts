import { useQuery } from '@tanstack/react-query';

import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api } from '@/lib/api/http';
import type {
  BorrowProposal,
  Chain,
  Coverage,
  FeePolicy,
  FeeSetting,
  Forecast,
  GovernanceTx,
  Hex,
  Treasury,
  TreasurySummary,
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

export const useTreasuries = (orgId: string) =>
  useOrgQuery<{ items: TreasurySummary[] }>(
    orgId,
    'treasuries',
    [],
    '/treasuries',
  );

interface TreasurySetupResponse {
  treasury: {
    id: string;
    chainId: number;
    assetId: string;
    status: string;
    coverage: Coverage;
    moduleAddress: Hex | null;
    createdAt: string;
  };
  wallets: Array<{
    role: 'SOURCE' | 'OPERATIONAL';
    label: string;
    safeAddress: Hex;
    owners: Hex[];
    threshold: number;
  }>;
}

function normalizeTreasurySetup(
  data: TreasuryState | TreasurySetupResponse,
  chains: Chain[],
): TreasuryState {
  if ('wallets' in data && 'activity' in data) return data;
  const chain = chains.find(
    (item) => item.chainId === data.treasury.chainId,
  );
  const asset = chain?.assets.find(
    (item) => item.id === data.treasury.assetId,
  );
  if (!chain || !asset) {
    throw new Error(
      `Could not resolve asset ${data.treasury.assetId} on chain ${data.treasury.chainId}. Treasury setup cannot continue safely.`,
    );
  }
  let operationalIndex = 0;
  const wallets = data.wallets.map((item) => {
    const role: WalletRole =
      item.label === 'T' || item.label === 'O1' || item.label === 'O2'
        ? item.label
        : item.role === 'SOURCE'
          ? 'T'
          : operationalIndex++ === 0
            ? 'O1'
            : 'O2';
    return {
      role,
      label: role === 'T' ? 'Treasury Safe' : role === 'O1' ? 'Payments Safe' : 'Second operational Safe',
      safeAddress: item.safeAddress,
      balance: '0',
      buffer: '0',
      target: '0',
      threshold: item.threshold,
      owners: item.owners,
    };
  });
  return {
    treasury: {
      id: data.treasury.id,
      name: 'Operating treasury',
      chainId: data.treasury.chainId,
      chainName: chain.name,
      asset,
      moduleAddress: data.treasury.moduleAddress ?? `0x${'0'.repeat(40)}`,
      status: data.treasury.moduleAddress ? 'Active' : 'Setup',
    },
    wallets,
    coverage: data.treasury.coverage,
    mandate: null,
    budgets: [],
    staleness: { blockNumber: 0, observedAt: data.treasury.createdAt, stale: true },
    position: {
      safeUsdc: '0', aUsdc: '0', poolLiquidity: '0',
      requiredReserve: { paymentReserve: '0', floor: '0', holds: '0', total: '0' },
      availableForSupply: '0', supplyApyBps: 0,
      lastAction: { kind: 'NONE', amount: '0', at: data.treasury.createdAt, explanation: 'No activity yet.' },
    },
    queues: { approvals: 0, governance: 0, review: 0, reconciliation: 0 },
    activity: [],
  };
}

/** Verified Safes and coverage only: balances, module and staleness are placeholders, so keep this key apart from useTreasury. */
export const useTreasurySetup = (orgId: string, treasuryId: string | undefined) => {
  return useQuery<TreasuryState>({
    queryKey: ['org', orgId, 'treasury', treasuryId, 'setup'],
    enabled: Boolean(treasuryId),
    queryFn: async () => {
      const [data, chainResponse] = await Promise.all([
        api.get<TreasuryState | TreasurySetupResponse>(
          `/orgs/${orgId}/treasuries/${treasuryId}`,
        ),
        api.get<{ chains: Chain[] }>('/chains'),
      ]);
      return normalizeTreasurySetup(data, chainResponse.chains);
    },
  });
};

export const useForecast = (
  orgId: string,
  treasuryId: string,
  includeDrafts = false,
) =>
  useOrgQuery<Forecast>(
    orgId,
    'treasury',
    [treasuryId, 'forecast', String(includeDrafts)],
    `/treasuries/${treasuryId}/forecast${
      includeDrafts ? '?includeDrafts=true' : ''
    }`,
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
    api.post<{ treasury: { id: string } }>(`/orgs/${orgId}/treasuries`, {
      chainId: input.chainId,
      assetId: input.assetId,
      wallets: input.wallets.map(({ role, safeAddress }) => ({
        role: role === 'T' ? 'SOURCE' : 'OPERATIONAL',
        // Stable labels let the API identify the offending Safe on verification errors.
        label: role,
        safeAddress,
      })),
    }),
  );

export interface ModuleSetupInput {
  mandate: {
    validFrom: string;
    expiresAt: string;
    payeeCoolingSeconds: number;
    executor: string;
    guardian: string;
    pay: { perRequest: string; daily: string };
    refill: { perRequest: string; daily: string };
    supply: { perRequest: string; daily: string };
    approvalMaxAge: number;
    approvers: string[];
  };
  buffers: Array<{ wallet: string; minimum: string; target: string }>;
}

export interface ModuleSetupResponse {
  governanceTx: GovernanceTx;
  operationalGovernanceTxs: GovernanceTx[];
  predictedModuleAddress: Hex;
  status: 'ModulePending';
}

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
  useOrgMutation(
    orgId,
    (input: { treasuryId: string; setup: ModuleSetupInput }) =>
      api.post<ModuleSetupResponse>(
        `${base(orgId, input.treasuryId)}/module/deploy-tx`,
        input.setup,
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
