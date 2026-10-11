# M02 · Treasury & Chain Configuration (`api` + `worker`)

**Status:** Detailed (spec completion pass, 2026-10-11 — *(mặc định)* = proposal accepted by default, open for review) · **Path:** `docs/modules/treasury/` · **Code:** `services/api/.../treasury/` · **Epic:** `[EPIC] M02 · Treasury & Chain Configuration`
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

## 6. Interfaces (API_SPEC §2)

| Method | Endpoint | Perm | Errors |
|---|---|---|---|
| GET | `/chains` | auth | |
| POST | `/orgs/{o}/treasuries` | OWN, ADM | 422 `NOT_A_SAFE`, `WRONG_CHAIN`, `DUPLICATE_WALLET`, `UNSUPPORTED_ASSET`, `SAFE_VERSION_UNSUPPORTED`, `OWNER_SETS_DIFFER` (warning) |
| GET | `/orgs/{o}/treasuries/{t}` | ANY | |
| POST | `/orgs/{o}/treasuries/{t}/module/governance-tx` | OWN | → `{governanceTx}` (factory.create + enableModule ×3 via MultiSend on T; enableModule on O1/O2 as separate Safe txs) |
| POST | `/orgs/{o}/treasuries/{t}/coverage/refresh` | OWN, ADM | 503 `RPC_UNAVAILABLE` |
| POST | `/orgs/{o}/treasuries/{t}/coverage/acknowledge` | OWN | `{reason}`; 409 `COVERAGE_COMPLETE` |
| POST | `/orgs/{o}/safes/deploy-tx` (P2) | OWN | `{owners, threshold}` → tx for the wallet |

## 7. Flows

Setup wizard: choose chain (Sepolia) and asset (tUSDC or Circle USDC) → enter T/O1/O2 addresses (or deploy, P2) → verify Safes → module governance tx on T (factory.create; enable on T) → enable on O1 and O2 (each Safe signs its own `enableModule` — same owners, PH-9) → TreasuryModuleCreated observed → coverage → Guardian Safe setup (MDT-010) → mandate (M03).

## 8. Algorithms

- **Safe verification:** `getCode` non-empty; proxy `masterCopy` (storage slot 0) ∈ allowlisted Safe v1.4.1 singletons (L1/L2); `VERSION() == "1.4.1"`; chain id matches. EOAs → `NOT_A_SAFE`.
- **Owner sets:** T, O1, O2 should share owners and threshold (PH-9); differences produce a warning, not an error *(mặc định)*.
- **Coverage:** for each Safe: `modules = getModulesPaginated(SENTINEL, 10)`; expect exactly `[clone]` with `clone`'s EIP-1167 target = implementation; `getStorageAt(GUARD_SLOT) == 0`; fallback handler ∈ allowlist. Result per wallet + overall (worst of three).
- **Decimals:** `decimals()` on-chain must equal config; mismatch refuses the asset.

## 9. Configuration

Chain list and deployments from config + manifest (fail fast at startup: missing RPC, missing code hash, < 2 RPC URLs). Coverage refresh 10 min + events. Supported Safe version 1.4.1 only in M1 *(mặc định)*.

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
| M02-D2 | Safe v1.4.1 only. *(mặc định)* |
| M02-D3 | Coverage = exactly our clone + no guard + canonical fallback handler on all three Safes. |
| M02-D4 | PARTIAL allowed only with Owner acknowledgment; UNKNOWN never allows execution. |
| M02-D5 | Module setup via governance txs (MDT-009); O1/O2 enable their module with their own Safe txs. |
| M02-D6 | Differing owner sets warn, do not block. *(mặc định)* |
| M02-D7 | Coverage refresh every 10 min + on Safe config events. *(mặc định)* |
| M02-D8 | Config and deployments are files validated at startup; no runtime edit in M1. |
| M02-D9 | Decimals verified on-chain when an asset is added. |
| M02-D10 | Safe deployment from the UI is P2 (TRS-008). |
