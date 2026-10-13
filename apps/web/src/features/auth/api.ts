import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, isApiError } from '@/lib/api/http';
import type { Hex, Me, User } from '@/lib/api/types';

export const meKey = ['me'] as const;

/** The signed-in user, or `null` when there is no session. */
export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async (): Promise<Me | null> => {
      try {
        return await api.get<Me>('/me');
      } catch (error) {
        if (isApiError(error) && error.status === 401) return null;
        throw error;
      }
    },
    staleTime: 60_000,
  });
}

export function useRequestMagicLink() {
  return useMutation({
    mutationFn: (email: string) =>
      api.post<void>('/auth/magic-link', { email }),
  });
}

export function useVerifyMagicLink() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      api.post<{ user: User }>('/auth/magic-link/verify', { token }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSuccess: () => {
      queryClient.setQueryData(meKey, null);
      queryClient.removeQueries({ queryKey: ['org'] });
    },
  });
}

export function useLinkWallet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      address: Hex;
      chainId: number;
      signMessage: (message: string) => Promise<Hex>;
    }) => {
      const { nonce } = await api.get<{ nonce: string }>('/auth/siwe/nonce');
      const message = siweMessage(input.address, input.chainId, nonce);
      const signature = await input.signMessage(message);
      return api.post<{ address: Hex }>('/me/wallets', { message, signature });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

export function useUnlinkWallet() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (address: Hex) => api.delete<void>(`/me/wallets/${address}`),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

/** EIP-4361 message. The server checks the nonce, domain and address. */
export function siweMessage(address: Hex, chainId: number, nonce: string) {
  const { host, origin } = window.location;
  return [
    `${host} wants you to sign in with your Ethereum account:`,
    address,
    '',
    'Link this wallet to your TreasuryPilot account. This does not move funds.',
    '',
    `URI: ${origin}`,
    'Version: 1',
    `Chain ID: ${chainId}`,
    `Nonce: ${nonce}`,
    `Issued At: ${new Date().toISOString()}`,
  ].join('\n');
}
