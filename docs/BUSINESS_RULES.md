# TreasuryPilot: Business Rules

**Status:** Draft for gate G1 · **Date:** 2026-10-10

Business rules are **invariants of the business**, independent of UI or implementation. Each rule lists where it is **enforced**:
- **C** = smart contract (hard enforcement, cannot be bypassed by the backend)
- **B** = backend / policy engine (deterministic)
- **U** = UI (guidance only)

**No business-critical rule is enforced only by an LLM or a prompt.**

Default values marked *(default, O#)* come from the source docs' proposed options, which were adopted in decision Q8. They can be changed through `OPEN_QUESTIONS.md` before activation.

## 1. Authority & approval

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-001 | No payment is executed without a valid approval by an authorized human approver over the exact payment fields. | C, B | R1, D1 |
| BR-002 | The agent never creates obligations, changes payee or amount, raises limits, edits policy, adds payees, or approves invoices. | C, B | D1, Autonomy §1 |
| BR-003 | An approval binds: request_id, invoice hash, fingerprint, chainId, contract, treasury, paying wallet, asset, payee, amount, deadline, confirmed-terms hash, and expiry. Any change to these fields invalidates the approval. | C, B | UC-01, R1 |
| BR-004 | The contract verifies approvals cryptographically (EIP-712, domain-bound to chain and contract). A backend "approved" flag is never sufficient. | C | R1 |
| BR-005 | Maker-checker: the creator or last editor of a request cannot approve it. Solo mode, if enabled, is visibly flagged and audited. | B (C: approver set) | Q13 |
| BR-006 | Signer roles (Owner, Approver, Guardian) act only through linked wallets. App login alone grants no on-chain authority. | C, B | GA p.11 |

## 2. Mandate & permission structure

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-010 | Permission to execute = **valid approval AND active mandate AND current step satisfies every constraint**. These are three separate conditions, and none substitutes for another. | C, B | Domain §4 |
| BR-011 | The agent's allowed actions are limited to `REFILL`, `PAY` and `SWAP` (as mandated). Forbidden: arbitrary calls, unlimited `approve`, `delegatecall`, changing owners, modules, guard or fallback handler, and unchecked router calldata. | C | Domain §4.1 |
| BR-012 | M1 refills only along mandated paths from `T` to operational wallets. Refill between operational wallets is `Later` (F-059) and requires an explicit path. | C | D4 |
| BR-013 | PAY only to payees on the on-chain allowlist whose cooling period has ended. An unknown or cooling payee → BLOCK, even with an exception. | C | D3, S2 |
| BR-014 | A mandate missing any required field cannot be activated (gas cap, buffer/target per wallet, router and quote parameters if SWAP is enabled, expiry). | B, C | Domain §4.2 |
| BR-015 | Mandate creation, changes, pause and revoke take effect only after on-chain confirmation. Until then, the previous state governs. | C, B | UC-01, UC-05 |
| BR-016 | A new mandate version invalidates outstanding one-time exceptions and does not reset counters. | C | Domain §6.2 |
| BR-017 | Payee cooling period default: 24 hours (production) and 5 minutes (demo). An address change creates a new payee entry and restarts cooling. | C | S2 *(default)* |
| BR-018 | Protected mode requires complete module coverage. If another module able to move funds is enabled, autonomous execution is suspended until the Owner explicitly acknowledges the partial coverage. | B | GA p.20 |

## 3. Limits & counters

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-020 | Limits are expressed in **token base units**, not USD. One stablecoin is never assumed to equal 1 USD. | C | D2 |
| BR-021 | The daily window is the **UTC calendar day**: `day = floor(block.timestamp / 86400)`. It is not a rolling 24h window. | C | O3 *(default)* |
| BR-022 | Counters are keyed `(treasury, action, asset, day)` and are shared across all wallets and mandate versions. Changing the wallet or version never resets them. | C | R3 |
| BR-023 | PAY, REFILL and SWAP-input budgets are separate. A refill does not consume the vendor-payment budget, but consumes its own refill budget. | C | R3, Domain §5.1 |
| BR-024 | The full approved amount is paid in one PAY. Splitting a request to evade caps, or paying an invoice partially, is forbidden. | C, B | Domain §4.1, §3.3 |
| BR-025 | A reverted transaction does not increment usage counters. Its gas cost is still recorded and reported. | C, B | Domain §5.1, §5.4 |
| BR-026 | A step pending across UTC midnight is checked against the budget of the day it actually executes. Budget authority does not carry over from the previous day. | C | Domain §5.1 |

## 4. Liquidity

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-030 | No agent-path transaction may leave any wallet below its minimum buffer (`F`), including the source wallet `T` (`F_T`). | C | R4 |
| BR-031 | The target balance (`H ≥ F`) is a soft goal. The agent never refills only to reach the target when there is no shortage. | B | Domain §3.2 |
| BR-032 | `Shortage = max(0, ProtectedOther + D + F − B)`; `PreferredRefill = max(0, ProtectedOther + D + H − B)`; `Cap = min(SourceCapacity, RemainingRefillBudget, PerRefillLimit)`. If `Cap ≥ Preferred` → refill Preferred. If `Shortage ≤ Cap < Preferred` → refill Shortage and report that the target was not reached. | B | Domain §3 |
| BR-033 | If `Cap < Shortage` → STOP and report. No partial refill or partial payment. | B | Domain §3.3 |
| BR-034 | Every amount used for execution is computed by the deterministic calculator. An LLM never computes or asserts amounts, balances or permissions. | B | Autonomy §2–3 |
| BR-035 | Funds reserved for other registered obligations (`R_other`) and execution holds (`L_other`) are protected in planning (M1: backend; Later: on-chain, F-028). | B (Later: C) | Domain §3.1, §5.2 |

## 5. Exceptions

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-040 | A one-time exception lifts **only** the per-request cap. It never lifts the daily cap, buffer, payee allowlist or cooling, asset, chain or expiry. | C | O2 *(default)* |
| BR-041 | An exception binds request_id, mandate id and version, treasury, chain, contract, paying wallet, payee, asset, exact amount, expiry and nonce. It is consumed atomically with the payment, and only once. | C | Domain §6.1 |
| BR-042 | The full amount of an exception payment counts toward the daily PAY budget. | C | Domain §6.1 |
| BR-043 | Only the Owner can grant an exception. The AI may draft the request but never grants it. | C, B | D3 |

## 6. Planning & execution

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-050 | Execution is sequential: at most one request's step chain executes at a time per treasury. | B | Use-Case §3 |
| BR-051 | State (balances, mandate, counters, payee status) is re-read before every step. No step relies on a snapshot taken before an earlier step changed the state. | B | Use-Case §3 |
| BR-052 | The scheduling objective, in strict priority: (1) no hard-rule violation; (2) meet every feasible deadline; (3) maximize confirmed discounts captured minus late fees incurred; (4) minimize transaction count and fees. Ties are broken by approval order. The baseline (B1) is earliest-deadline-first. | B | N2, O8 *(default)*, Problem Statement §2 |
| BR-053 | A request is `Paid` only after the PAY transaction reaches the configured confirmation depth. `Paid` ≠ `Matched`. | B | UC-03 |
| BR-054 | Multi-step plans are not atomic. Completed steps are recorded as completed; they are never silently rolled back or redone. | B | Domain §3.3 |
| BR-055 | The rule-based fallback is used only when the AI is unavailable **and** data is complete **and** a tested template matches **and** no transaction is Unknown **and** there is no safety alert. It is recorded as `RULE_BASED`. | B | D6 |
| BR-056 | An AI plan that is invalid or out of mandate is discarded and routed to NeedsReview. It is never repaired by loosening policy, and never hidden behind the fallback. | B | Autonomy §5 |
| BR-057 | Allow and block reasons shown to users come from the validator. AI text is shown separately, labelled as explanation. | B, U | Autonomy §5 |
| BR-058 | AI confidence scores are never used as a permission condition. | B | Autonomy §6 |
| BR-059 | Execution requires a plan attestation over the exact plan (planHash, policy version, nonce, expiry). Steps that differ from the attested plan are rejected. | B (C where verified on-chain) | GA p.21–22 |

## 7. Recovery & emergency

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-060 | Pending, timeout or lost connection ≠ failed. No new request and no second payment is created until the previous outcome is determined. Execution for the treasury is blocked while any operation is Unknown. | B, C (replay) | R8 |
| BR-061 | Retries reuse the same request_id, step_id, operation id and idempotency key. | B, C | UC-04 |
| BR-062 | Pause and revoke block new execution after they take effect on-chain. Confirmed transactions are never reversed, and the product never promises reversal. | C | R9 |
| BR-063 | When a pause is requested, the backend stops planning and submitting immediately, even before the on-chain pause is confirmed. | B | R9 |
| BR-064 | Only the Owner can resume. The Guardian can only pause. | C | GA p.23 |
| BR-065 | Circuit-breaker defaults: at least 3 contract rejections in 10 minutes, any AI plan out of mandate, a coverage drop, or a post-condition discrepancy → backend auto-pause and notify the Owner. | B | S7 *(default)* |

## 8. Invoices & data

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-070 | Invoice and vendor content is untrusted **data**, never an instruction to the agent. | B | Use-Case §2 |
| BR-071 | Duplicate fingerprint (`vendor, invoiceNo, amount, asset`) → the backend blocks submission, and the contract blocks a second PAY. Override requires an Owner-signed flag inside the approval. | C, B | S3 |
| BR-072 | An invoice address that differs from the registered payee or vendor history raises a high-severity flag. Changing a payee's address requires the Owner's payee update plus a new cooling period. An invoice can never change a payee. | B, C | N1, S2 |
| BR-073 | M1 invoices must be denominated in the treasury's payment stablecoin. | B | Q20 |
| BR-074 | Only hashes and commitments are stored on-chain. Invoice documents and personal data stay off-chain in private storage. | B | Use-Case §2 |
| BR-075 | AI-extracted fields and terms are drafts until a human confirms them. Only confirmed terms influence scheduling. | B | N1 |

## 9. Gas, swap & assets

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-080 | The executor's gas is prefunded. Gas funding from treasury wallets is capped separately. Native gas is never a PAY asset to vendors. The gas funding cap does not cap actual network fees. | C, B | Domain §5.4, O6 *(default)* |
| BR-081 | Swaps go only through allowlisted adapter, router and pairs, within the swap budget, with a fresh quote from the configured source. `minOut = ceil(quoteOut × (10000 − maxSlippageBps) / 10000)` is computed by the engine and cannot be lowered by the agent. | C, B | R5 |
| BR-082 | The swap allowance equals exactly the input and is reset to 0 in the same transaction. | C | GA p.22 |
| BR-083 | Assets are identified by `(chainId, address)`. Decimals are verified on-chain. All arithmetic uses integer base units. | B, C | Domain §2 |

## 10. Compliance & platform

| ID | Rule | Enforced | Source |
|---|---|---|---|
| BR-085 | A payee that matches the sanctions or blocklist cannot be registered or paid. If the screening provider is unavailable, registration fails closed. PAY may rely on a cached clean result within its TTL; otherwise it blocks. | B | S6 |
| BR-090 | Non-goals: no speculative trading, yield, lending, staking or portfolio management. The contract exposes no such actions. | C | D5 |
| BR-091 | TreasuryPilot never takes custody of customer funds. Funds stay in customer-owned Safes. | C (architecture) | D5 |
| BR-092 | No owner key ever reaches TreasuryPilot. The executor key lives in a separate signer service. LLM processes receive no secrets. | Architecture | Domain §6.2 |
| BR-093 | Data of one organization is never accessible to another (tenant isolation). | B | Q3 |
| BR-094 | PlatformAdmin has no capability to sign or move customer funds. | Architecture | Q13 |
| BR-095 | Test assets, routers and fixtures are labelled everywhere. Scenario tooling refuses non-allowlisted (mainnet) chains. Evidence never contains fabricated transaction hashes. | B | AT §6, GA p.31 |
| BR-096 | Classification: a refill is an internal transfer, a swap is a conversion, and a payment is an external expense. `Matched` requires matching evidence. | B | UC-03 |
| BR-097 | Every action that affects money or authority is written to the audit log. If the audit write fails, the financial action fails closed. | B | S6 |
