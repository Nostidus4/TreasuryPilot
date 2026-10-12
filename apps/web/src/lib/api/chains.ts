import { useQuery } from '@tanstack/react-query';

import { api } from '@/lib/api/http';
import type { Asset, Chain } from '@/lib/api/types';

export function useChains() {
  return useQuery({
    queryKey: ['chains'],
    queryFn: () => api.get<{ chains: Chain[] }>('/chains'),
    staleTime: Infinity,
    select: (data) => data.chains,
  });
}

/** M1 runs on one chain; `chainId` narrows it once more chains exist. */
export function useChain(chainId?: number): Chain | undefined {
  const { data } = useChains();
  return chainId ? data?.find((chain) => chain.chainId === chainId) : data?.[0];
}

export function useAssetInfo(
  asset?: Asset,
): { asset: Asset; chain: Chain } | undefined {
  const chain = useChain();
  if (!chain) return undefined;
  return { asset: asset ?? chain.assets[0], chain };
}
