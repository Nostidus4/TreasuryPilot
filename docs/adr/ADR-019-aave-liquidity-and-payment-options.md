# ADR-019: Adopt spec v0.3 — Aave idle-cash management and two-option payment approvals

**Status:** Accepted (2026-10-11, team lead's spec v0.3 reviewed in a grilling round) · **Source:** `docs/source/TreasuryPilot-v0.3-team-lead-spec.md` · **Decisions:** V3-1 … V3-14

## Context
The team lead's specification v0.3 widens the MVP from "REFILL/PAY only, no lending" to an autonomous on-chain treasury manager that also keeps idle USDC productive in Aave V3, and binds early-payment discounts into the approval itself. Our architecture (Python, Safe + one custom module, CP-SAT scheduler, policy attestation) stays; v0.3 is merged into it.

## Decision
| ID | Decision |
|---|---|
| V3-1 | **Aave V3 SUPPLY / WITHDRAW are autonomous** M1 actions of the module, through fixed calls to one allowlisted Pool for the treasury asset only. aTokens stay in Safe T. |
| V3-2 | **BORROW / REPAY:** M1 delivers a **borrow proposal** only (cost vs withdraw, health factor before/after, reason) with no transaction (demo D6). Owner-authorized execution is **P2** (D7). |
| V3-3 | **Payment approval with two options:** `PaymentApproval` gains `earlyAmount` and `earlyPayBy`. Before `earlyPayBy` the contract pays exactly `earlyAmount` (if set); otherwise exactly `amount` (standard) until `expiry`. One request is consumed once. This replaces "discount captured while paying the full amount". |
| V3-4 | **Backend stays Python** (FastAPI, web3.py); Viem only in the web app (via wagmi). |
| V3-5 | **Optimizer stays OR-Tools CP-SAT** (ADR-015); v0.3's objective (late fees + lost discount + borrow interest + gas − supply interest) is added as integer terms, still behind obligations and mandate in priority. |
| V3-6 | **One operational wallet in the demo** (T + O1). Contract and specs keep a list of operational wallets. |
| V3-7 | **Asset on Sepolia = Aave's test USDC** (`0x94a9…E4C8`, Aave faucet, label TEST). `tUSDC` + a mock Pool only for local/CI. The Circle USDC evidence run stays PAY-only (Aave does not list Circle's Sepolia USDC). |
| V3-8 | **On-chain reserve protection:** the module enforces an Owner-set **Safe floor** (static, in the mandate) and **supply caps** (per tx, per day); the dynamic **PaymentReserve** (approved, unpaid obligations) is enforced by the off-chain validator. Withdraw is always autonomous and returns funds to Safe T, so an over-supply costs at most one cycle. Documented as a known risk. |
| V3-9 | **Supply hysteresis:** supply only when `AvailableForSupply ≥ minSupply` (Owner-set; demo 500); withdraw the deficit + 5 % margin; at most one SUPPLY or WITHDRAW per execution cycle. |
| V3-10 | **Single module**, new fixed functions `supply`, `withdraw` (and `borrow`, `repay` behind owner authorization, P2); Pool and aToken addresses fixed in the module at initialization (registry); interfaces kept separate. |
| V3-11 | **Testing:** unit tests against a MockAavePool; integration on an Anvil fork of Sepolia at a pinned block; demo on Sepolia. |
| V3-12 | **Judge demo D1–D10** (refill+pay, supply surplus, withdraw for new invoice, unknown payee, cap breach, borrow proposal, signed borrow (P2), AI outage, unknown tx, guardian pause) become scenario files and runbook scenes. |
| V3-13 | **Benchmark adds B0** (manual / EDF with idle cash) before B1 (deterministic optimizer) and B2 (AI + optimizer). |
| V3-14 | **Config gate:** CI fails if chain id, token decimals or Aave Pool/aToken mapping differ from `deployments/<chainId>.json`; addresses only from official deployment data. Evidence package carries a disclosure: testnet, synthetic data, no legal approval, no audit, no yield guarantee. |

## Formulas (M07)
```
RequiredSafeReserve = PaymentReserve + OperatingBuffer(=Safe floor) + DebtServiceReserve + ExecutionHolds
AvailableForSupply  = max(0, SafeUSDC − RequiredSafeReserve)
AccessibleLiquidity = SafeUSDC + min(aUSDC, PoolAvailableUSDC)
```
PaymentReserve = Σ amounts (early or standard, whichever the schedule chose) of approved, unpaid requests due within the reserve horizon (30 days).

## Consequences
- BR-090 is revised (supply/withdraw of the treasury stablecoin into one allowlisted lending pool is allowed; speculation, leverage, other assets remain non-goals; borrow only with owner authorization).
- PaymentApproval EIP-712 type changes (13 fields): SC-002/005/006/017, ENG-010, INV-010, WEB-009 revised.
- New tickets for supply/withdraw, Aave reads, reserve formulas, borrow proposal, fork tests, position UI, B0 baseline, D1–D10 scenarios, config gate.
- ADR-012 revised (asset). Tier A grows by about 8–10 dev-days.
