import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type PropsWithChildren,
} from 'react';
import { privateKeyToAccount } from 'viem/accounts';
import {
  useAccount,
  useConnect,
  useDisconnect,
  useSendTransaction,
  useSignMessage,
  useSignTypedData,
  useSwitchChain,
} from 'wagmi';

import type { Hex, TxCall, TypedData } from '@/lib/api/types';
import { mockApiEnabled } from '@/lib/env';

/**
 * One wallet surface for the app.
 *
 * - `injected`: the user's browser wallet through wagmi.
 * - `demo`: a local Anvil key, offered only while the mock API is on, so the
 *   signing flows work without a browser wallet. It produces real EIP-712
 *   signatures that the mock API verifies.
 *
 * While the mock API is on, `sendTransaction` never broadcasts: there are no
 * contracts behind the fixture addresses.
 */
export interface Wallet {
  address?: Hex;
  chainId?: number;
  kind: 'injected' | 'demo' | null;
  hasInjected: boolean;
  demoAvailable: boolean;
  connecting: boolean;
  connect: (kind: 'injected' | 'demo') => Promise<void>;
  disconnect: () => void;
  switchChain: (chainId: number) => Promise<void>;
  signMessage: (message: string) => Promise<Hex>;
  signTypedData: (typedData: TypedData) => Promise<Hex>;
  sendTransaction: (call: TxCall) => Promise<Hex>;
}

// Anvil's first default account. Public test key: never holds real funds.
const demoAccount = privateKeyToAccount(
  '0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80',
);
const demoKey = 'treasurypilot.demo-wallet';

const WalletContext = createContext<Wallet | null>(null);

function readDemoFlag() {
  try {
    return window.sessionStorage.getItem(demoKey) === 'on';
  } catch {
    return false;
  }
}

function simulatedHash(): Hex {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return `0x${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

export function WalletProvider({ children }: PropsWithChildren) {
  const account = useAccount();
  const { connectAsync, connectors, isPending } = useConnect();
  const { disconnect: disconnectInjected } = useDisconnect();
  const { signMessageAsync } = useSignMessage();
  const { signTypedDataAsync } = useSignTypedData();
  const { sendTransactionAsync } = useSendTransaction();
  const { switchChainAsync } = useSwitchChain();

  const [demo, setDemo] = useState(() => mockApiEnabled && readDemoFlag());
  const [demoChainId, setDemoChainId] = useState(11155111);
  const hasInjected =
    typeof window !== 'undefined' &&
    'ethereum' in window &&
    connectors.length > 0;

  const setDemoFlag = useCallback((on: boolean) => {
    setDemo(on);
    try {
      if (on) window.sessionStorage.setItem(demoKey, 'on');
      else window.sessionStorage.removeItem(demoKey);
    } catch {
      /* the choice lasts for this page only */
    }
  }, []);

  const value = useMemo<Wallet>(() => {
    const kind = demo ? 'demo' : account.isConnected ? 'injected' : null;
    return {
      address: demo ? demoAccount.address : account.address,
      chainId: demo ? demoChainId : account.chainId,
      kind,
      hasInjected,
      demoAvailable: mockApiEnabled,
      connecting: isPending,
      connect: async (target) => {
        if (target === 'demo') {
          setDemoFlag(true);
          return;
        }
        setDemoFlag(false);
        await connectAsync({ connector: connectors[0] });
      },
      disconnect: () => {
        if (demo) setDemoFlag(false);
        else disconnectInjected();
      },
      switchChain: async (chainId) => {
        if (demo) setDemoChainId(chainId);
        else await switchChainAsync({ chainId });
      },
      signMessage: (message) =>
        demo
          ? demoAccount.signMessage({ message })
          : signMessageAsync({ message }),
      // The object the server built is passed through unchanged (M16-D1).
      signTypedData: (typedData) => {
        const payload = typedData as unknown as Parameters<
          typeof demoAccount.signTypedData
        >[0];
        return demo
          ? demoAccount.signTypedData(payload)
          : signTypedDataAsync(
              payload as Parameters<typeof signTypedDataAsync>[0],
            );
      },
      sendTransaction: async (call) => {
        if (mockApiEnabled) return simulatedHash();
        return sendTransactionAsync({
          to: call.to,
          data: call.data,
          value: BigInt(call.value ?? '0'),
        });
      },
    };
  }, [
    account.address,
    account.chainId,
    account.isConnected,
    connectAsync,
    connectors,
    demo,
    demoChainId,
    disconnectInjected,
    hasInjected,
    isPending,
    sendTransactionAsync,
    setDemoFlag,
    signMessageAsync,
    signTypedDataAsync,
    switchChainAsync,
  ]);

  return (
    <WalletContext.Provider value={value}>{children}</WalletContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useWallet(): Wallet {
  const wallet = useContext(WalletContext);
  if (!wallet) throw new Error('useWallet must be used inside WalletProvider');
  return wallet;
}

/** True when the wallet declined the request (EIP-1193 code 4001). */
// eslint-disable-next-line react-refresh/only-export-components
export function isUserRejection(error: unknown): boolean {
  let current: unknown = error;
  for (let depth = 0; depth < 5 && current; depth += 1) {
    const candidate = current as {
      code?: number;
      name?: string;
      cause?: unknown;
    };
    if (
      candidate.code === 4001 ||
      candidate.name === 'UserRejectedRequestError'
    ) {
      return true;
    }
    current = candidate.cause;
  }
  return false;
}
