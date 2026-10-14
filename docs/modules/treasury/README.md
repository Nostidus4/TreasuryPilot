# M02 · Treasury & Chain Configuration (`api` + `worker`)

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/treasury/` · **Code:** `services/api/.../treasury/` · **Epic:** `[EPIC] M02 · Treasury & Chain Configuration`
**ADRs:** ADR-002 (Safe + module), ADR-012 (Ethereum Sepolia), ADR-014 (money) · **Decisions:** M02-D1 … M02-D10 (§14)

---

## 1. Purpose and boundaries

M02 registers **what a treasury is**: one chain, one payment stablecoin, one source Safe **T** and operational Safes **O1, O2**, the module clone that governs them, and whether that module is the **only** thing able to move funds (coverage).

| In scope (M1) | Out of scope |
|---|---|
| Platform chain config and deployments manifest | Mandate content (M03) |
| Asset registry with on-chain decimals and test labels | Reading balances for planning (M06) |
| Treasury creation with Safe verification | Multiple treasuries/assets (Later) |
| Safe config snapshots and change detection | |
| Module deploy (factory) + enable on T/O1/O2 (via MDT-009) | |
| Coverage computation and Owner acknowledgment | |
| Optional Safe deployment from the UI (P2) | |

## 2. Features, requirements and rules

F-010 (FR-101–102), F-011 (FR-103–105), F-012 (FR-106–107, BR-018), F-013 (FR-108–109, BR-083), F-151 (FR-925); Later F-014/F-015.

## 3. Concepts

| Term | Definition |
|---|---|
| **Treasury** | `(org, chain, asset, T, {O1, O2}, module)`. Status `Draft → ModulePending → Ready → (Paused) → Revoked`. |
| **Coverage** | COMPLETE: each Safe's modules = {our clone whose implementation is the known one}, no guard (or an allowlisted guard), fallback handler = canonical. PARTIAL: anything else. UNKNOWN: read failed. |
| **Coverage acknowledgment** | Owner accepts PARTIAL explicitly ("protected mode off"); audited; banner shown; execution allowed (BR-018). |
| **Deployments manifest** | `deployments/<chainId>.json`: implementation, factory, tUSDC, Circle USDC, Safe singletons, MultiSendCallOnly, Multicall3, EAS + schema UID, code hashes. |

## 4. Data model (DATA_MODEL §2.2)

`chains` (11155111, confirmations 3, explorer, RPC urls), `assets` (tUSDC is_test, Circle USDC), `deployments`, `treasuries` (+ status, module_address, coverage, coverage_ack_*), `treasury_wallets` (role SOURCE/OPERATIONAL, label, safe_address, owners, threshold), `safe_config_snapshots`.

## 5. State

Treasury: `Draft` (Safes verified) → `ModulePending` (deploy+enable governance tx Collecting/Submitted) → `Ready` (module recorded, coverage computed) → `Revoked` (module revoked). Pause is shown from M03. Coverage: `UNKNOWN ⇄ PARTIAL ⇄ COMPLETE` recomputed on Safe config events and every 10 min.

The worker reads each active Safe at one pinned block every 10 minutes and appends a block-hash-unique `safe_config_snapshots` row, including its fallback handler and the EIP-1167 implementation target (if any) for each enabled module. Coverage is recomputed in the snapshot transaction and by the Owner/Admin refresh endpoint. A missing or older-than-12-minute snapshot (also evaluated on every read), a treasury without a module, a missing expected deployment, or any failed or malformed chain read leaves coverage UNKNOWN. An acknowledgment applies only to the exact PARTIAL deviations the Owner reviewed: any change in the coverage details clears it. An Owner can acknowledge PARTIAL coverage with a reason; the audit log records that action and the acknowledgment state is returned to clients as a persistent banner state. `executionAllowed` is true only for COMPLETE or acknowledged PARTIAL coverage.

The chain deployment manifest must include `TREASURY_MODULE_IMPLEMENTATION` and `SAFE_FALLBACK_HANDLER` before coverage can become COMPLETE. The current Sepolia record is still `configured_only`, and its deployment-record/API-manifest shape is documented as unreconciled; do not treat the configured-only address fields as a live deployment. TRS-006 (#44) remains open, so this issue does not claim module deployment, enablement, or a mined module-created event.

## 6. Interfaces (API_SPEC §2)

| Method | Endpoint | Perm | Errors |
|---|---|---|---|
| GET | `/chains` | auth | |
| POST | `/orgs/{o}/treasuries` | OWN, ADM | 422 `NOT_A_SAFE`, `WRONG_CHAIN`, `DUPLICATE_WALLET`, `UNSUPPORTED_ASSET`, `SAFE_VERSION_UNSUPPORTED`, `OWNER_SETS_DIFFER` (warning) |
| GET | `/orgs/{o}/treasuries/{t}` | ANY | |
| POST | `/orgs/{o}/treasuries/{t}/module/governance-tx` | OWN | → `{governanceTx}` (factory.create + enableModule ×3 via MultiSend on T; enableModule on O1/O2 as separate Safe txs) |
| POST | `/orgs/{o}/treasuries/{t}/coverage/refresh` | OWN, ADM | 503 `RPC_UNAVAILABLE` |
| POST | `/orgs/{o}/treasuries/{t}/coverage/acknowledge` | OWN | `{reason}`; 409 `COVERAGE_COMPLETE` |
| POST | `/orgs/{o}/safes/deploy-tx` (P2) | OWN, ADM | `{chainId, owners, threshold}` → `{chainId, transaction:{to,data,value}}`; 503 `SAFE_DEPLOYMENT_UNAVAILABLE` until verified Safe deployment entries are configured |

## 7. Flows

Setup wizard: choose chain (Sepolia) and asset (tUSDC or Circle USDC) → enter T/O1/O2 addresses (or request a Safe factory transaction when deployment config is verified) → verify Safes → module governance tx on T (factory.create; enable on T) → enable on O1 and O2 (each Safe signs its own `enableModule` — same owners, PH-9) → TreasuryModuleCreated observed → coverage → Guardian Safe setup (MDT-010) → mandate (M03).

## 8. Algorithms

- **Safe verification:** `getCode` non-empty; proxy `masterCopy` (storage slot 0) ∈ allowlisted Safe v1.4.1 singletons (L1/L2); `VERSION() == "1.4.1"`; chain id matches. EOAs → `NOT_A_SAFE`.
- **Safe deployment:** the deploy-tx endpoint only builds `createProxyWithNonce` calldata when the API manifest explicitly includes `SAFE_SINGLETON_L1` or `SAFE_SINGLETON_L2` (version `1.4.1`), `SAFE_PROXY_FACTORY`, and `SAFE_FALLBACK_HANDLER`, each with a non-zero address and code hash; the endpoint also verifies all three runtime code hashes against a configured RPC before returning a transaction. Legacy scalar fields in the contracts deployment manifest do not satisfy this requirement. Current Sepolia API configuration lacks these entries, so the wizard reports deployment unavailable and the endpoint returns 503; existing Safe creation remains available.
- **Implementation (TRS-004):** `treasury/safe.py` reads the chain through the configured HTTP RPC providers (failover, all reads pinned to one block) with the Safe ABI instead of safe-eth-py, whose web3 8 / eth-account 0.13 pins cannot resolve in this workspace. The singleton allowlist is the manifest deployments `SAFE_SINGLETON_L1` and `SAFE_SINGLETON_L2` with version `1.4.1`; none configured fails closed with `SAFE_VERSION_UNSUPPORTED`. A Safe belongs to one treasury across all tenants (`DUPLICATE_WALLET`). Creation is audited as `treasury.created`. Request: `{chainId, assetId, wallets[{role, safeAddress, label?}]}` with one SOURCE and one or two OPERATIONAL wallets; `OWNER_SETS_DIFFER` is returned in `warnings`; no RPC answer gives 503 `RPC_UNAVAILABLE`.
- **Owner sets:** T, O1, O2 should share owners and threshold (PH-9); differences produce a warning, not an error.
- **Coverage:** for each Safe, use the latest fresh snapshot: modules must equal `[clone]`, the clone's exact EIP-1167 runtime must target `TREASURY_MODULE_IMPLEMENTATION`, `getStorageAt(GUARD_SLOT) == 0`, and the fallback handler must equal the configured `SAFE_FALLBACK_HANDLER`. Any extra module, unexpected guard, wrong clone target, or wrong fallback handler yields PARTIAL; missing/stale snapshots or missing configured expectations yield UNKNOWN. The execution gate allows COMPLETE and Owner-acknowledged PARTIAL only.
- **Decimals:** `decimals()` on-chain must equal config; mismatch refuses the asset.

## 9. Configuration

Chain list and deployments from config + manifest (fail fast at startup: missing RPC, missing code hash, < 2 RPC URLs). Coverage refresh 10 min + events. Supported Safe version 1.4.1 only in M1.

## 10. Security

Coverage prevents "another module drains the Safe" blind spots; acknowledgment is explicit and audited; config is not editable at runtime in M1; test assets labelled everywhere (BR-095).

## 11. Failure scenarios

RPC failure → coverage UNKNOWN (never COMPLETE) → execution gate closed; Owner adds a module elsewhere → event → PARTIAL → circuit breaker PAUSE (M12); wrong decimals → asset refused.

## 12. Test plan

Integration on Anvil with real Safe v1.4.1: verification (Safe vs EOA vs wrong version); module setup through MDT-009; coverage COMPLETE, then add a dummy module → PARTIAL, add a guard → PARTIAL, RPC down → UNKNOWN; acknowledgment audited.

## 13. Tickets

TRS-001 → TRS-002 → TRS-003 → TRS-004 → TRS-005 → TRS-006 → TRS-007 → TRS-008 (P2). Later TRS-L01/L02.

## 14. Decisions

| ID | Decision |
|---|---|
| M02-D1 | Ethereum Sepolia; assets tUSDC (test) and Circle USDC (ADR-012). |
| M02-D2 | Safe v1.4.1 only. |
| M02-D3 | Coverage = exactly our clone + no guard + canonical fallback handler on all three Safes. |
| M02-D4 | PARTIAL allowed only with Owner acknowledgment; UNKNOWN never allows execution. |
| M02-D5 | Module setup via governance txs (MDT-009); O1/O2 enable their module with their own Safe txs. |
| M02-D6 | Differing owner sets warn, do not block. |
| M02-D7 | Coverage refresh every 10 min + on Safe config events. |
| M02-D8 | Config and deployments are files validated at startup; no runtime edit in M1. |
| M02-D9 | Decimals verified on-chain when an asset is added. |
| M02-D10 | Safe deployment from the UI is P2 (TRS-008). |

## 15. v0.3 changes (ADR-019)

The deployments manifest adds `AAVE_POOL`, `AAVE_POOL_ADDRESSES_PROVIDER`, `ATOKEN` and the Aave test USDC; the demo treasury is T + one operational Safe (O1). Coverage rules are unchanged (the module calls Aave through Safe T; Aave is not a Safe module).
