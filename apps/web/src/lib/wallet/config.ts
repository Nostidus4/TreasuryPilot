import { http, createConfig } from 'wagmi';
import { foundry, sepolia } from 'wagmi/chains';
import { injected } from 'wagmi/connectors';

const localRpcUrl = import.meta.env.VITE_RPC_URL ?? 'http://localhost:8545';

export const wagmiConfig = createConfig({
  chains: [foundry, sepolia],
  connectors: [injected()],
  transports: {
    [foundry.id]: http(localRpcUrl),
    [sepolia.id]: http(),
  },
});
