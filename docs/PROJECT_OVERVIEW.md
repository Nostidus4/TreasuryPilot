# TreasuryPilot: Project Overview

**Status:** Draft for review gate G1 · **Version:** 0.3 (derived from source docs v0.2) · **Date:** 2026-10-10
**Sources:** `TreasuryPilot.md` v0.2, the score-improvement plan, mechanisms adopted from GuardianAI, the FigJam board. See `docs/decisions-log.md`.

> **One line:** TreasuryPilot is an AI treasury operator that gets *approved* invoices paid on time. It moves liquidity between a company's own wallets and settles on-chain. A smart-contract mandate guarantees that it can never pay the wrong party, exceed the budget, or touch the safety buffer.

---

## 1. What is this project?

### The product
TreasuryPilot is a web application with an on-chain enforcement layer. A business that pays suppliers in stablecoins connects its company wallets, sets spending rules once, and approves invoices. An AI agent handles the rest of the job:

- It reads invoices, including messy PDFs, and extracts their payment terms.
- It works out when each invoice should be paid.
- It moves money from the company's treasury wallet into the wallet that pays.
- It pays the supplier on-chain.
- It reconciles each payment against the invoice.

### Who uses it
- **Primary:** finance and treasury operators, founders, and approvers at stablecoin-native SMEs and Web3 businesses.
- **Secondary:** accountants, auditors, and security-minded owners.

See §4.

### Why it exists
Two problems block these businesses:

1. **Money is often in the wrong place.** The company has enough money in total, but the wallet that must pay is short of the right token or gas. Someone has to move funds by hand before every payment run.
2. **Automating this means trusting an agent with money.** A prompt is not a control.

TreasuryPilot exists to automate the work while keeping control provable. **Humans decide *whether* to pay. The agent decides *how and when*. The contract makes sure it cannot do anything else.**

### When it is used
- A supplier invoice arrives, by upload, CSV, or later by email or API.
- Approved invoices approach their due date or an early-payment-discount window.
- An operational wallet runs low ahead of upcoming obligations.
- An exception occurs: an invoice is over the per-payment cap, a payee address has changed, a transaction is stuck, or a pause is requested.
- Month-end, when finance needs payments matched to invoices with evidence.

---

## 2. Problem Statement

Format: **User → Situation → Problem → Consequence.** Unless marked *(evidence)*, statements are hypotheses to validate (H1–H7 in the source doc).

| # | User | Situation | Problem | Consequence |
|---|---|---|---|---|
| P1 | Treasury operator | An approved invoice is due. The paying wallet `O1` holds less stablecoin or gas than needed, while treasury wallet `T` has plenty. | The operator must check balances, compute the shortfall, choose a source, transfer, wait for signatures, and then pay. Every step is manual. | Late payments, operator hours per payment run, and errors such as a wrong amount, a wrong network, or a duplicate refill. *(Evidence of manual payment and reconciliation effort: Request Finance case, Whatever Digital, 40+ contractors/month. Evidence of a "USDC but no gas" failure: Acurast docs.)* |
| P2 | Founder or owner | They want to automate payments with an agent or script. | Existing delegation tools are limited. Safe spending limits do not restrict *who* receives money *(evidence: Safe docs)*. A prompt cannot stop an agent from paying a malicious address. | They either keep signing every step, which leaves the bottleneck in place, or they over-delegate and take on unbounded risk. |
| P3 | Approver | Invoices arrive as PDFs and emails containing free text. | A fraudster can change a supplier's address ("updated wallet details"), and an injected instruction can try to steer an AI. Duplicate invoices also slip in under new IDs. | Funds go to the wrong address, which is irreversible on-chain. This is the classic vendor/BEC fraud pattern. |
| P4 | Finance lead | Several approved invoices compete for limited liquidity and a daily budget. Some carry early-payment discounts ("2/10 net 30"); others carry late fees. | Choosing the order by hand ignores terms. Simple rules such as "earliest due first" leave money on the table. | Missed discounts, late fees, and avoidable exception requests. |
| P5 | Accountant / auditor | Payments span refills, swaps, and the payment itself. | Matching transaction hashes to invoices is manual. Internal transfers get mis-booked as expenses. | Slow month-end close and weak audit evidence. |

**Why existing solutions fall short.** Sources: market research of 10/10/2026, `docs/research/FinTechathon2026-Evaluation-GuardianAI-vs-TreasuryPilot.md` §5.

| Existing option | What it does well | Gap TreasuryPilot targets |
|---|---|---|
| Request Finance | Invoices, batch crypto payouts, accounting | Does not *prepare liquidity* across wallets. No bounded autonomous agent. |
| Safe Spending Limits / Zodiac Roles | On-chain delegated limits | Not bound to *approved invoices*. No buffer protection, planning, or reconciliation. |
| Coinbase Agentic Wallets | Agent wallets with spending caps and KYT | Not an AP workflow. No maker-checker or invoice-bound authority. |
| Fireblocks / Utila | Institutional policy engines | Enterprise cost and complexity. No AI planning over invoice terms. |
| Ant International Whale | AI-triggered top-ups for Ant's own treasury | Internal to one conglomerate. Not an SME product with an owner-set mandate. |
| Scripts / cron | Cheap, deterministic refill | Do not read terms, detect fraud signals, explain decisions, or handle exceptions. |

---

## 3. Product Vision

**Today:** check balances → detect shortfall → choose source → (swap/bridge) → wait for signatures → refill → pay → reconcile. Every step is done by hand, often across explorers, spreadsheets, and a multisig UI.

**With TreasuryPilot:**

| Step | Who does it |
|---|---|
| Configure the mandate once: wallets, payees, limits, buffer, validity | **Owner** signs on-chain |
| Intake invoices and extract fields, payment terms, and red flags | **AI** proposes; a human verifies the diff |
| Approve *whether* to pay this exact invoice (amount, payee, asset, deadline) | **Approver** signs (EIP-712) |
| Decide *when and in which order* to pay, and how much to refill | **AI** proposes; the **deterministic optimizer and policy engine** compute and validate |
| Execute refill, swap and pay within the mandate | **Executor**, checked by the **contract** |
| Over-cap invoice | **AI** drafts the exception; the **Owner** grants a one-time exception |
| Verify, reconcile, export, attest | **System**; **Finance** marks Matched |
| Pause or revoke | **Owner / Guardian**, at any time |

**AI authority.** The AI may observe, recommend, and explain. It may choose among *already-valid* options. It **never** holds keys, computes amounts used for payment, approves invoices, edits policy, adds payees, or bypasses a check. Its outputs pass through deterministic validation, and the contract is the final authority.

---

## 4. Target Users

### Primary users
| Persona | Description | Goals | Fears |
|---|---|---|---|
| **Mai, Treasury Operator** at a 25-person Web3 SaaS company | Runs weekly vendor and contractor payouts in USDC across 3 wallets | No late payments, fewer manual transfers | Paying twice, paying the wrong address |
| **Daniel, Founder / Org Owner** | Holds the Safe owner key and sets policy | Delegate safely and sleep at night | An agent draining the treasury |
| **Linh, Approver / Finance Lead** | Approves invoices | Approve fast with confidence; catch fraud | Approving a tampered invoice |

### Secondary users
| Persona | Role |
|---|---|
| **Accountant** | Exports reconciliation and books entries, separating internal transfers from expenses |
| **Auditor** | Read-only access to evidence: approvals, plans, tx hashes, decisions |
| **Guardian** | Security contact who can only pause |
| **Org Admin** | Manages members and roles |

### Enterprise / partner users (`Later`)
- **Platform Admin** at TreasuryPilot: tenant operations. Never touches customer funds.
- **Integrators:** ERP/accounting systems (Xero, QuickBooks, NetSuite), compliance providers (KYB/KYT), notification platforms, and stablecoin issuers or payment partners.

---

## 5. Main User Journeys

**J1. Onboarding and mandate setup**
Org Admin signs up → creates the organization → invites members and assigns roles → Owner connects or creates the Safes (T, O1, O2) → enables the TreasuryPilot module → configures the mandate (actions, wallets, refill paths, payees, limits, buffer, validity) → signs the on-chain activation → the system waits for confirmation, verifies the enabled modules (coverage), and marks the mandate **Active**.

**J2. Payee onboarding** (anti-fraud)
Owner adds a payee address → it is screened against the blocklist/sanctions list → a **cooling period** starts → the payee becomes usable only after the period ends. Address changes restart the cycle.

**J3. Invoice intake → approval**
Operator uploads a PDF, imports a CSV, or enters an invoice manually → AI extracts the fields and payment terms and flags anomalies (address differs from history, amount outlier, duplicate fingerprint, injected instructions) → the operator confirms the draft → the approver sees the diff and flags and signs EIP-712 approval of the exact fields → the request becomes **Approved** and its fingerprint is registered.

**J4. Autonomous planning and execution** (the core job)
The deadline trigger fires → the system reads a fresh state → the calculator computes shortages → the terms-aware scheduler and AI propose an order and plan with explanations → the policy engine validates (ALLOW / NEEDS_APPROVAL / BLOCK) → the plan is attested (planHash, nonce, expiry) → the executor submits step by step (REFILL → [SWAP] → PAY) → the contract re-checks every rule → after each step the system confirms and re-reads → the request is **Paid** → reconciliation runs.

**J5. Over-cap exception**
The validator returns NEEDS_APPROVAL → AI drafts the exception request with its reasoning → the Owner reviews and signs a one-time exception bound to that exact request → the system re-validates and resumes J4. The daily cap still applies.

**J6. Recovery**
A transaction is pending or unknown, or the executor crashes → the system looks up the receipt and contract state by the *same* identifiers → it holds or resumes with no second payment → partial completions (for example a refill done but the payment blocked) are reported, never rolled back silently.

**J7. Emergency stop**
The Guardian or Owner pauses, or the circuit breaker auto-pauses → the backend stops submitting immediately → the pause takes effect on-chain after confirmation → completed transactions are not reversed → only the Owner can resume.

**J8. Reconciliation and audit**
Finance opens the reconciliation view (request ↔ tx hashes ↔ fees ↔ classification) → marks **Matched** or flags a discrepancy → exports CSV/journal entries and the evidence bundle → optionally an on-chain attestation is published.

**J9. Copilot what-if**
The Owner asks, for example, "Can we pay everything due this week without breaching the buffer?" → the Copilot runs a policy-engine simulation (read-only) → answers with numbers, a proposed plan, and the constraints that bind.

**J10. Notifications**
Events such as a needed approval, an exception, a payment made, a pause, or an anomaly reach users in-app and on Telegram, with deep links to sign in the web app.

---

## 6. Value Proposition

| Instead of… | TreasuryPilot gives… | Proof we will show |
|---|---|---|
| Manually moving funds before every payout | Automatic, mandate-bound refill and payment | Tx hashes; operator minutes and interventions per batch |
| Trusting a script or agent blindly | Contract-enforced limits: payee allowlist + cooling period, per-request and daily caps, buffer, replay protection, pause | Invariant/fuzz tests; on-chain reverts for bypass attempts |
| "Earliest due first" | Terms-aware scheduling that captures discounts and avoids late fees within liquidity | B1 (rule) vs B2 (AI) benchmark in stablecoin saved |
| Approving invoices blind | A diff view with fraud signals (address change, duplicates, injected text) | Red-team suite results |
| Spreadsheet reconciliation | Automatic linking of request ↔ tx ↔ fee, internal transfers classified, export and attestation | Exported CSV and an evidence bundle |

**Blast-radius guarantee:** even if the executor key is compromised, it cannot pay an invoice without an approver's signature, cannot pay an unregistered or cooling payee, and cannot exceed the daily cap. Funds can only move between the company's own wallets, within limits.

---

## 7. Product Scope

The full inventory, with IDs and phases, is in `FEATURES.md`.

### Core capabilities
Mandate-bound execution (REFILL, PAY, SWAP) · approved-invoice lifecycle · liquidity calculation and refill planning · terms-aware scheduling · one-time exceptions · pause and revoke · reconciliation.

### Supporting capabilities
Invoice intake (manual, PDF, CSV; email and API later) · payee registry with cooling period · duplicate fingerprinting · liquidity forecast · reconciliation export · notifications (in-app, Telegram; email, webhook and chat platforms later).

### Platform capabilities
Multi-tenant organizations · multi-treasury and multi-chain-ready model · asset registry · signer service · job orchestration · billing (later) · developer experience (one-command environment, CI, scenario runner).

### AI capabilities
Invoice intelligence (extraction, payment terms, anomaly flags) · plan proposal and explanation · exception drafting · Copilot what-if · prompt-injection defense · rule-based fallback · B1/B2 evaluation harness.

### Admin capabilities
Org Admin (members, roles, maker-checker) · Platform Admin (tenants, chain/RPC/asset configuration) · mandate and policy editor.

### Security / compliance capabilities
On-chain mandate enforcement · EIP-712 approvals and plan attestation · circuit breaker · sanctions/blocklist screening (KYB, KYT and Travel Rule later) · hash-chained audit log · evidence bundle · coverage and uncertainty labels · data minimization (only invoice hashes on-chain).

### Non-goals (never in scope)
Speculative trading · yield optimization · lending · portfolio management · custody of customer funds · paying unapproved invoices · the agent autonomously purchasing services · reversing confirmed transactions.

---

## 8. FigJam board vs this inventory (gaps to port)

The FigJam board covers J1, J4, J5, J6 and J7 well. It **does not yet show:** invoice intake and AI intelligence (J3), payee cooling period (J2), duplicate fingerprinting, terms-aware scheduling and the savings metric, deadline trigger, plan attestation, Copilot (J9), notifications (J10), reconciliation export and attestation (J8), the circuit breaker, sanctions screening, multi-tenant roles, or the platform admin. The board's "TBD" boxes (Authority Guard, RPC, Quote source, Swap router) are resolved in Phase 3 ADRs.
