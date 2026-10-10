# ADR-012: M1 chain and stablecoin
**Status:** **Open — owner: anh Phúc** (OQ-02, OQ-03)

## Options and BA recommendation
- **Chain:** Base Sepolia (recommended), fallback Ethereum Sepolia.
  - Verify: Safe singleton/factory deployments and the safe-eth-py support for the chain; Circle testnet USDC faucet; EAS availability; ≥2 RPC providers; explorer API.
- **Stablecoin:** Circle testnet USDC for the demo + team-deployed `tUSDC` (labelled TEST) for automated runs.
  - Verify faucet limits against ~40+ runs.

## Blocks
Deployment manifest, F-010/F-013/F-074/F-151, seed scripts, demo runbook.
