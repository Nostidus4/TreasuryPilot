# ADR-012: M1 chain and stablecoin
**Status:** **Accepted** (anh Phúc, 2026-10-11) · OQ-01, OQ-02, OQ-03, OQ-05 · Decisions PH-1 … PH-3

## Decision
- **Chain:** **Ethereum Sepolia** (chainId 11155111). 12 s blocks. Safe v1.4.1 and the Safe Transaction Service are available; EAS is deployed at `0xC2679fBD37d54388Ce493F1DB75320D236e1815e` (to re-verify in DOM-001).
- **Asset:** a team-deployed **`tUSDC`** (6 decimals, labelled TEST) for the main demo and all automated runs, keeping the demo limits (2,000 / 10,000 pay; 2,500 / 12,000 refill). Plus **one evidence run with Circle's testnet USDC on Sepolia** with every limit divided by 100, because the Circle faucets give 10 USDC per day (public) or 10 × 20 USDC per day per team (developer console).
- **Evidence:** public testnet transactions are acceptable (anh Phúc). This is the team's interpretation of the published checklist (item 06 requires real on-chain transaction hashes and does not specify the network); organizer confirmation is optional and non-blocking (OQ-01, DOM-003).

## Revision (ADR-019, 2026-10-11)
Aave V3 on Sepolia lists only its own test USDC (`0x94a9…E4C8`, Aave faucet). The **treasury asset on Sepolia becomes Aave's test USDC** (label TEST); `tUSDC` remains for local/CI with a mock Pool; the Circle USDC run stays PAY-only. The demo uses one operational wallet (T + O1).

## Token addresses (DOM-002, #230)
Checked on Sepolia on 2026-10-16 with `symbol()`, `name()` and `decimals()` over RPC.

| Use | Token | Sepolia address | Decimals | Source |
| --- | --- | --- | --- | --- |
| Treasury asset (ADR-019), D1-D10 on Sepolia | Aave test USDC, labelled TEST | `0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8` | 6 | Aave faucet; `deployments/11155111.json` `asset` |
| Evidence run, PAY-only | Circle USDC | `0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238` | 6 | Circle faucet (faucet.circle.com / developer console) |
| Local/CI (Anvil) | `tUSDC`, labelled TEST | CREATE2, recorded as `testToken` in `deployments/31337.json` | 6 | `Deploy.s.sol` |

`tUSDC` deployment parameters (`contracts/src/test-assets/TestUSDC.sol`): name `TEST USD Coin`, symbol `tUSDC`, 6 decimals, open `mint` (anyone can mint, so it has no value). `Deploy.s.sol` also deploys it on Sepolia as a separately labelled test asset; it is never the treasury asset there.

## Consequences
- Confirmations: Paid after 3 blocks (~36 s), configurable (PH-5). Snapshot freshness ≤ 2 blocks (M08).
- RPC: Alchemy primary + public Sepolia RPC fallback (PH-8).
- Deployment with CREATE2 and Etherscan verification (PH-10).
- Base Sepolia remains a documented fallback.

## Sources
Circle faucet limits: developers.circle.com/w3s/developer-console-faucet · Safe networks: docs.safe.global/api-supported-networks
