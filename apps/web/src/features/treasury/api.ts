import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { useOrgMutation, useOrgQuery } from '@/lib/api/hooks';
import { api, errorMessage, isApiError } from '@/lib/api/http';
import type { components } from '@/lib/api/schema';
import { t } from '@/lib/i18n';
import type {
  BorrowProposal,
  Chain,
  Coverage,
  FeePolicy,
  FeePolicyResponse,
  FeeReviewItem,
  Forecast,
  GovernanceTx,
  Hex,
  TreasuryStatus,
  TreasurySummary,
  TreasuryState,
  TreasuryWallet,
  WalletRole,
} from '@/lib/api/types';

const base = (orgId: string, treasuryId: string) =>
  `/orgs/${orgId}/treasuries/${treasuryId}`;

type ApiTreasury = components['schemas']['TreasuryResponse'];

/**
 * Dashboard parts the API does not return yet (TRS-009). They pass through when
 * present (the mock serves them) and stay undefined otherwise; never fake them.
 */
type TreasuryExtras = Partial<
  Pick<
    TreasuryState,
    | 'mandate'
    | 'budgets'
    | 'staleness'
    | 'position'
    | 'queues'
    | 'activity'
    | 'borrowProposalId'
  >
>;
type TreasuryResponse = Omit<ApiTreasury, 'wallets'> & {
  wallets: Array<
    ApiTreasury['wallets'][number] &
      Partial<Pick<TreasuryWallet, 'balance' | 'buffer' | 'target'>>
  >;
} & TreasuryExtras;

const treasuryStatusFromApi: Record<
  components['schemas']['TreasuryStatus'],
  TreasuryStatus
> = {
  Draft: 'Setup',
  ModulePending: 'Setup',
  Ready: 'Active',
  Paused: 'Paused',
  Revoked: 'Revoked',
};

export function toTreasuryState(
  data: TreasuryResponse,
  chains: Chain[],
): TreasuryState {
  const {
    treasury,
    wallets: apiWallets,
    warnings: _warnings,
    ...extras
  } = data;
  const chain = chains.find((item) => item.chainId === treasury.chainId);
  const asset = chain?.assets.find((item) => item.id === treasury.assetId);
  if (!chain || !asset) {
    throw new Error(
      `Could not resolve asset ${treasury.assetId} on chain ${treasury.chainId}.`,
    );
  }
  let operationalIndex = 0;
  const wallets = apiWallets.map((item): TreasuryWallet => {
    const role: WalletRole =
      item.label === 'T' || item.label === 'O1' || item.label === 'O2'
        ? item.label
        : item.role === 'SOURCE'
          ? 'T'
          : operationalIndex++ === 0
            ? 'O1'
            : 'O2';
    return {
      id: item.id,
      role,
      label: item.label,
      safeAddress: item.safeAddress as Hex,
      balance: item.balance,
      buffer: item.buffer,
      target: item.target,
      threshold: item.threshold,
      owners: item.owners as Hex[],
    };
  });
  return {
    ...extras,
    treasury: {
      id: treasury.id,
      // The API has no treasury name; same label as the org's treasury list.
      name: `${chain.name} · ${asset.symbol}`,
      chainId: treasury.chainId,
      chainName: chain.name,
      asset,
      moduleAddress: (treasury.moduleAddress ?? `0x${'0'.repeat(40)}`) as Hex,
      status: treasuryStatusFromApi[treasury.status],
    },
    wallets,
    coverage: treasury.coverage,
  };
}

const fetchTreasuryState = async (orgId: string, treasuryId: string) => {
  const [data, chainResponse] = await Promise.all([
    api.get<TreasuryResponse>(`/orgs/${orgId}/treasuries/${treasuryId}`),
    api.get<{ chains: Chain[] }>('/chains'),
  ]);
  return toTreasuryState(data, chainResponse.chains);
};

export const useTreasury = (orgId: string, treasuryId: string | undefined) =>
  useQuery<TreasuryState>({
    queryKey: ['org', orgId, 'treasury', treasuryId],
    enabled: Boolean(treasuryId),
    queryFn: () => fetchTreasuryState(orgId, treasuryId!),
  });

export const useTreasuries = (orgId: string) =>
  useOrgQuery<{ items: TreasurySummary[] }>(
    orgId,
    'treasuries',
    [],
    '/treasuries',
  );

/** The setup wizard polls its own key so its refreshes do not churn the dashboard. */
export const useTreasurySetup = (
  orgId: string,
  treasuryId: string | undefined,
) =>
  useQuery<TreasuryState>({
    queryKey: ['org', orgId, 'treasury', treasuryId, 'setup'],
    enabled: Boolean(treasuryId),
    queryFn: () => fetchTreasuryState(orgId, treasuryId!),
  });

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
    // Keep the chart mounted while the other variant loads.
    { placeholderData: keepPreviousData },
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

const num = (value: unknown, fallback = 0) =>
  typeof value === 'number' && Number.isFinite(value) ? value : fallback;
const wei = (value: unknown) =>
  typeof value === 'string' && /^\d+$/.test(value) ? value : '0';

/** Maps the backend fee-policy response to what the page renders; tolerates missing parts. */
export function normalizeFeePolicy(
  data: Partial<FeePolicyResponse> | null | undefined,
): FeePolicy {
  const proposal = data?.proposal ?? null;
  return {
    proposalId: proposal?.id ?? null,
    active: data?.active ?? null,
    proposal,
    basis: {
      avgPlanFeeWei: wei(proposal?.basis?.avgPlanFee7dWei),
      p90PlanFeeWei: wei(proposal?.basis?.p90PlanFee7dWei),
      plansPerDay: num(proposal?.basis?.plansPerDay7d),
    },
    spentTodayWei: wei(data?.spentTodayWei),
    history: data?.history ?? [],
  };
}

/** Fee acceptance needs a recent second factor; the web app has no step-up prompt yet. */
export const feeErrorMessage = (error: unknown) =>
  isApiError(error, 'STEP_UP_REQUIRED')
    ? t(
        'Step-up required: confirm your second factor (POST /v1/me/mfa/step-up), then try again.',
      )
    : errorMessage(error);

export const useFeePolicy = (orgId: string, treasuryId: string) =>
  useQuery<FeePolicy>({
    queryKey: ['org', orgId, 'treasury', treasuryId, 'fees'],
    queryFn: async ({ signal }) =>
      normalizeFeePolicy(
        await api.get<FeePolicyResponse>(
          `${base(orgId, treasuryId)}/fee-policy`,
          {
            signal,
          },
        ),
      ),
  });

/** Plans held for a fee decision are the open FEE_APPROVAL items of the review queue. */
export const useHeldFeePlans = (orgId: string, treasuryId: string) =>
  useOrgQuery<{ items: FeeReviewItem[] }>(
    orgId,
    'review',
    ['fee-approval'],
    '/review-items',
    {
      query: { status: 'Open', type: 'FEE_APPROVAL' },
      select: (data) => ({
        items: data.items.filter(
          (item) =>
            item.treasuryId === treasuryId &&
            item.planId &&
            item.feeEstimateWei !== null,
        ),
      }),
    },
  );

export const useAcceptFeePolicy = (orgId: string, treasuryId: string) =>
  useOrgMutation(
    orgId,
    (input: components['schemas']['FeePolicyAcceptRequest']) =>
      api.post<{ active: unknown }>(
        `${base(orgId, treasuryId)}/fee-policy/accept`,
        input,
      ),
  );

// useOrgMutation refreshes every org query, which includes the review queue behind held plans.
export const usePlanFeeDecision = (orgId: string, action: 'accept' | 'defer') =>
  useOrgMutation(orgId, (planId: string) =>
    api.post<{ planId: string }>(
      `/orgs/${orgId}/plans/${planId}/fee/${action}`,
      {},
    ),
  );

export const usePauseTreasury = (orgId: string, treasuryId: string) =>
  useOrgMutation(orgId, (reason: string) =>
    api.post<components['schemas']['PauseResponse']>(
      `${base(orgId, treasuryId)}/pause`,
      { reason },
      { idempotent: true },
    ),
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
