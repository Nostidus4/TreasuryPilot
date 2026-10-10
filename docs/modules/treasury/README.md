# M02 · Treasury & Chain Configuration

**Status:** Draft for gate G2 · **Path:** `docs/modules/treasury/`

## Purpose
Model treasuries (chain, payment asset, T + operational Safes), read Safe configurations, compute module coverage, and hold the chain/asset/deployment registry.

## Features
F-010, F-011, F-012, F-013, F-014 (Later), F-015 (Later), F-151

## Inputs
Treasury definitions, Safe addresses, chain config and deployment manifest, on-chain reads.

## Outputs
Treasury records, Safe config snapshots, a coverage status consumed by M10 (execution gate) and M16 (banner).

## APIs
`/chains`, `/orgs/{o}/treasuries…`, `/module/deploy-tx`, `/coverage/refresh`, `/coverage/acknowledge` (API_SPEC §2).

## Data model
chains, assets, deployments, treasuries, treasury_wallets, safe_config_snapshots

## Dependencies
M01 (auth), M06 chain-reader (reads), M04 contracts (module address, code hash), M15 audit.

## Security concerns
Fake Safe or EOA presented as a Safe (verify the proxy singleton and code hash); a rogue extra module (coverage PARTIAL blocks execution); wrong chainId (validate at creation); token impersonation (assets by address + decimals check).

## Failure scenarios
RPC failure → coverage UNKNOWN (never COMPLETE). Owner changes owners/threshold → snapshot diff → event and banner.

## Open questions
OQ-02 / OQ-03 chain and token (owner: Phúc).
