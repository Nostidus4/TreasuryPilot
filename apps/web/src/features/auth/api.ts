import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, isApiError, rememberCsrfToken } from '@/lib/api/http';
import { fromApiRoles } from '@/lib/api/roles';
import type { components } from '@/lib/api/schema';
import type { Hex, Me, User } from '@/lib/api/types';

type ApiMe = components['schemas']['MeResponse'];
type ApiUser = components['schemas']['UserView'];

const toUser = (user: ApiUser): User => ({
  id: user.id,
  email: user.email,
  name: user.displayName ?? user.email,
});

const toMe = (me: ApiMe): Me => ({
  user: toUser(me.user),
  memberships: me.memberships.map((item) => ({
    orgId: item.orgId,
    orgName: item.orgName,
    roles: fromApiRoles(item.roles),
  })),
  wallets: me.wallets.map((item) => ({
    address: item.address as Hex,
    linkedAt: item.linkedAt,
  })),
});

export const meKey = ['me'] as const;

/** The signed-in user, or `null` when there is no session. */
export function useMe() {
  return useQuery({
    queryKey: meKey,
    queryFn: async (): Promise<Me | null> => {
      try {
        return toMe(await api.get<ApiMe>('/me'));
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
    mutationFn: async (token: string) => {
      const { user, csrfToken } = await api.post<{
        user: ApiUser;
        csrfToken?: string;
      }>('/auth/magic-link/verify', { token });
      rememberCsrfToken(csrfToken ?? null);
      return { user: toUser(user) };
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: meKey }),
  });
}

export function useSignOut() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>('/auth/logout'),
    onSuccess: () => {
      rememberCsrfToken(null);
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
      signMessage: (message: string) => Promise<Hex>;
    }) => {
      // The API pins the SIWE chain id and nonce lifetime, whatever chain the wallet is on.
      const challenge = await api.get<
        Pick<
          components['schemas']['SiweNonceResponse'],
          'nonce' | 'expiresAt' | 'chainId'
        >
      >('/auth/siwe/nonce');
      const message = siweMessage(
        input.address,
        challenge.chainId,
        challenge.nonce,
        challenge.expiresAt,
      );
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

export interface MfaStatus {
  factors: Array<{ id: string; kind: string; label: string }>;
  recoveryCodesRemaining: number;
}

const mfaKey = ['me', 'mfa'] as const;

export const useMfaStatus = () =>
  useQuery({ queryKey: mfaKey, queryFn: () => api.get<MfaStatus>('/me/mfa') });

export const useStartTotp = () =>
  useMutation({
    mutationFn: () =>
      api.post<{ factorId: string; otpauthUri: string }>('/me/mfa/totp', {
        label: 'Authenticator app',
      }),
  });

export function useConfirmTotp() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: { factorId: string; code: string }) =>
      api.post<{ recoveryCodes: string[] }>(
        `/me/mfa/totp/${input.factorId}/confirm`,
        { code: input.code },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mfaKey }),
  });
}

/** A fresh second-factor check; the API accepts it for 10 minutes. */
export const useStepUp = () =>
  useMutation({
    mutationFn: (code: string) => api.post<void>('/me/mfa/step-up', { code }),
  });

/** EIP-4361 message. The server checks the nonce, domain and address. */
export function siweMessage(
  address: Hex,
  chainId: number,
  nonce: string,
  expiresAt: string,
) {
  const { host, origin, protocol } = window.location;
  // The scheme prefix is required: the API rejects a message without it on http origins.
  return [
    `${protocol}//${host} wants you to sign in with your Ethereum account:`,
    address,
    '',
    'Link this wallet to TreasuryPilot',
    '',
    `URI: ${origin}`,
    'Version: 1',
    `Chain ID: ${chainId}`,
    `Nonce: ${nonce}`,
    `Issued At: ${new Date().toISOString()}`,
    `Expiration Time: ${expiresAt}`,
  ].join('\n');
}
