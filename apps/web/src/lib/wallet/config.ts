import { http, createConfig } from 'wagmi';
import { foundry, sepolia } from 'wagmi/chains';
import { injected } from 'wagmi/connectors';

const isSepoliaBuild = import.meta.env.VITE_CHAIN_ID === String(sepolia.id);
// VITE_RPC_URL applies only to the configured chain; foundry keeps its local default.
const localRpcUrl = isSepoliaBuild
  ? 'http://localhost:8545'
  : (import.meta.env.VITE_RPC_URL ?? 'http://localhost:8545');
// Public RPC is the default; VITE_RPC_URL overrides it when the app targets Sepolia.
const sepoliaRpcUrl = isSepoliaBuild ? import.meta.env.VITE_RPC_URL : undefined;

export const wagmiConfig = createConfig({
  chains: [foundry, sepolia],
  connectors: [injected()],
  transports: {
    [foundry.id]: http(localRpcUrl),
    [sepolia.id]: http(sepoliaRpcUrl),
  },
});
