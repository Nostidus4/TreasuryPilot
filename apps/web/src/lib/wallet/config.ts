import { http, createConfig } from 'wagmi';
import { foundry, sepolia } from 'wagmi/chains';
import { injected } from 'wagmi/connectors';

const localRpcUrl = import.meta.env.VITE_RPC_URL ?? 'http://localhost:8545';
// Public RPC is the default; VITE_RPC_URL overrides it when the app targets Sepolia.
const sepoliaRpcUrl =
  import.meta.env.VITE_CHAIN_ID === String(sepolia.id)
    ? import.meta.env.VITE_RPC_URL
    : undefined;

export const wagmiConfig = createConfig({
  chains: [foundry, sepolia],
  connectors: [injected()],
  transports: {
    [foundry.id]: http(localRpcUrl),
    [sepolia.id]: http(sepoliaRpcUrl),
  },
});
