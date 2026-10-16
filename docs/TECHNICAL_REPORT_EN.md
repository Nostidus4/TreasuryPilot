# TreasuryPilot — Technical Report & Documentation Hub

> **Reviewed:** 16 October 2026 · **Code baseline:** commit `50b1117` · **Sources:** the current repository and the [TreasuryPilot Google Doc](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit), particularly tabs 8, 11, 13, 36 and 37. Historical measurements are identified by their date and environment.

**TL;DR — What does TreasuryPilot do?** TreasuryPilot receives invoices, requires an authorized person to confirm and approve the exact payment obligation, schedules payment, moves liquidity between an organization's own Safe wallets, executes through a constrained on-chain module, tracks the receipt, and reconciles the result. AI reads documents, proposes actions and explains decisions. Human signatures, deterministic policy checks, a separate signer and the smart contract control the movement of funds.

**How to read implementation status:** **Present in code** means a concrete implementation path exists. **Local evidence** means a test or report covers local/fork execution. **Sepolia configuration** means a deployment manifest contains addresses and verification metadata, without proving every end-to-end scenario. **Design or pending verification** means the intended behavior is documented or partly implemented but lacks evidence for a complete operational claim. Some repository READMEs and submission drafts describe older revisions; this report favors current code and dated evidence.

## 01 · Getting started

### 1.1 Problem and product boundary

The primary users are finance and treasury operators, payment approvers and company owners paying vendors in stablecoins. An approved invoice can still be late because the operational wallet lacks the right token or gas while the treasury wallet has funds. Moving funds manually, monitoring limits and assembling proof of payment are error-prone. Delegating an unrestricted wallet to an agent is unacceptable. The product's division of authority is: **humans decide whether to pay; the agent proposes how and when; the contract constrains what can be executed**. [Product overview](PROJECT_OVERVIEW.md) · [Google Doc overview](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.0).

M1 is a synthetic-asset Sepolia evaluation, not an audited mainnet payment service. Version 0.3 adds Aave V3 supply/withdraw for genuinely idle funds, an approved early-payment amount alongside the standard amount, and borrowing proposals. Contract code also implements owner-granted borrow/repay paths as a P2 capability; their existence does not mean the M1 product autonomously borrows. [Version 0.3 decisions](vi/37-cap-nhat-v03.md) · [existing technical draft](submission/technical-documentation.md).

### 1.2 End-to-end value flow

[![Payment request to verified transaction](report_site/diagrams/payment-flow.svg)](report_site/diagrams/payment-flow.svg)

*Figure 01.1 — End-to-end payment flow · [Edit in draw.io](report_site/diagrams/payment-flow.drawio).*

1. **Set up:** create an organization and treasury, connect Safe T (treasury) and Safe O1 (operational), select chain/asset, deploy the module, and set the mandate, payees, limits and balance floors.
2. **Intake:** enter or upload an invoice, store the document privately, extract fields and payment terms, and flag duplicates or anomalies.
3. **Confirm and approve:** a person confirms significant fields; backend maker-checker and HIGH-flag rules apply; an approver signs EIP-712 typed data for the exact obligation.
4. **Plan:** load a fresh chain snapshot and unpaid obligations; the deterministic engine calculates shortages, reserves and a schedule. AI may propose a choice, while policy returns `ALLOW`, `NEEDS_APPROVAL` or `BLOCK`.
5. **Execute:** persist the outbox record, create a policy attestation, let the isolated signer verify calldata and simulate fresh state, then submit steps in order. The module checks authority, caps, floors and replay protection again on-chain.
6. **Verify:** the tracker observes receipt and chain state, the verifier checks postconditions, reconciliation connects transfers to the request, and audit/evidence records the trail. An `Unknown` outcome must be resolved before a retry.

This is the **target system-wide sequence**. Individual components have code, while completion of the entire sequence depends on environment-specific smoke and end-to-end evidence. [System flow](SYSTEM_ARCHITECTURE.md) · [worker tasks](../services/worker/src/treasurypilot_worker/tasks.py) · [execution API](../services/api/src/treasurypilot_api/execution/routes.py).

### 1.3 Wallets and authority

| Actor or component | Purpose | Relevant authority |
|---|---|---|
| Safe T | Treasury wallet and mandate owner | Owner threshold governs configuration, exceptions, pause/revoke and Aave aTokens. |
| Safe O1/O2 | Operational company wallets | Receive request-bound refills and pay vendors through the module. The M1 demo uses O1; local fixtures may use O2. |
| Approver | Authorizes one payment obligation | Signs exact EIP-712 fields; this signature does not change the mandate. |
| Executor/signer | Broadcasts a checked transaction | Holds the executor key in a separate service; cannot change the payee or policy. |
| AI worker | Reads, proposes and explains | Read-only tools, no spending authority or signing key. |
| Contract module | Last gate for module-originated transfers | Checks authorization, payee, limit, floor, expiration and replay state at execution time. |

Safe owners or other enabled Safe modules can still make transactions outside TreasuryPilot. The mandate constrains the **TreasuryPilotModule path**, not every possible Safe action. [Known risk KR-02](security/known-risks.md) · [governance contract](../contracts/src/TreasuryPilotGovernance.sol).

## 02 · System architecture

### 2.1 Deployment layers

[![TreasuryPilot deployment and data flow](report_site/diagrams/system-architecture.svg)](report_site/diagrams/system-architecture.svg)

*Figure 02.1 — Deployment layers · [Edit in draw.io](report_site/diagrams/system-architecture.drawio).*

The implementation is divided into [web](../apps/web/src/app.tsx), [API](../services/api/src/treasurypilot_api/main.py), [worker](../services/worker/src/treasurypilot_worker/tasks.py), [signer](../services/signer/src/treasurypilot_signer/main.py), pure [py-core](../packages/py-core/src/treasurypilot_core/) and [contracts](../contracts/src/). PostgreSQL is the business source of truth. Redis dispatches work; it is not a payment ledger. [Compose](../infra/compose.yaml) separates core, AI and webhook workers, beat, signer, API, web, PostgreSQL, Redis and MinIO. Anvil is a local profile.

### 2.2 Trust boundaries

| Boundary | Untrusted or sensitive input | Control | Remaining limitation |
|---|---|---|---|
| Invoice → AI | PDF, email, free text | Untrusted-content wrapper, instruction/secret scans, schema and human confirmation | Independent adversarial evaluation is still needed. |
| Browser → API | Session, organization ID, signature | RBAC, maker-checker, scoped queries and session checks | Every new endpoint still needs review. |
| Worker → signer | Attestation, calldata and plan | Internal secret, typed checks, fresh simulation | Shared host or database credentials remain operational risks. |
| Signer → module | Signed transaction | Contract rechecks each action | `eth_call` does not reserve future block state. |
| Chain → backend | Balances, events and receipts | Chain ID, RPC health, confirmation and reorg handling | A stale/unavailable RPC can delay or distort interim conclusions. |

See [AI architecture](AI_AGENT_ARCHITECTURE.md), [signing service](../services/signer/src/treasurypilot_signer/service.py) and [known risks](security/known-risks.md).

### 2.3 Consistency rules

- **Money uses integer base units.** API and database serialize decimal integers; Python uses strict integer types; Solidity uses `uint256`. Floating point is excluded from payment decisions. [BaseUnits](../packages/py-core/src/treasurypilot_core/money/base_units.py).
- **Time is UTC.** Daily limits use chain block time; user-facing dates may use the organization's timezone. Due-date calculations normalize to UTC days. [UTC day helpers](../packages/py-core/src/treasurypilot_core/domain/utc_days.py).
- **Write before action.** Persist the operation and stable step identity before broadcast. A timeout is unknown, not failure. [Outbox](../services/worker/src/treasurypilot_worker/executor/outbox.py).
- **Evidence is built into the flow.** A decision must be traceable to policy version, hashes, transaction, receipt and verified postcondition. [Audit evidence](../services/api/src/treasurypilot_api/audit/evidence.py).

## 03 · Invoice and approval workflow

### 3.1 Request lifecycle

The draft/extraction state is separate from an executable obligation. Intake checks fields, payee, asset, fingerprint, terms and anomaly flags. The code exposes create/bulk, edit, terms confirmation, submit, withdraw/request changes, HIGH-flag acknowledgment, typed-data retrieval, approve, reject, cancel and renew operations. [Request routes](../services/api/src/treasurypilot_api/invoices/requests.py) · [state machine](../services/api/src/treasurypilot_api/invoices/state_machine.py) · [documents](../services/api/src/treasurypilot_api/invoices/documents.py).

Upload, API-key and inbound-email paths have implementation. The existence of an endpoint does not establish that a provider or mail integration is configured in a particular deployment. Fingerprints and near-duplicate checks address renamed/re-entered invoices, while the on-chain approval signature prevents a database `approved` flag alone from authorizing payment. [API keys](../services/api/src/treasurypilot_api/invoices/api_keys.py) · [email intake](../services/api/src/treasurypilot_api/invoices/inbound_email.py) · [fingerprint](../packages/py-core/src/treasurypilot_core/fingerprint/invoice.py).

### 3.2 Payment signature

`PaymentApproval` binds request ID, invoice hash, fingerprint, treasury, paying wallet, asset, payee, standard amount, early amount and early deadline, terms hash, expiry, and a fiat flag. Its EIP-712 domain binds chain and module. The module checks that the current approver signed (EOA or ERC-1271), selects the correct early or standard amount for the time window and consumes the request once. Fiat-quoted requests have separate cap semantics; therefore “every payment equals one fixed integer” would be too broad. [Approval hash](../contracts/src/libraries/PaymentApprovalHash.sol) · [module pay](../contracts/src/TreasuryPilotModule.sol) · [approval API](../services/api/src/treasurypilot_api/invoices/approval.py).

### 3.3 Maker-checker and fraud flags

Backend RBAC determines who creates, edits and approves a request. Maker-checker may prevent self-approval, with a distinct controlled solo mode. HIGH flags require acknowledgment or review before progression. A changed payee or signed field invalidates a stale approval. These backend controls are separate from the contract's signature verification. [Maker-checker](../services/api/src/treasurypilot_api/identity/maker_checker.py) · [RBAC](../services/api/src/treasurypilot_api/identity/rbac.py) · [risk KR-24](security/known-risks.md).

## 04 · Financial engine and optimization

### 4.1 Request-bound refill

For operational-wallet balance `B`, hard floor `F`, soft target `H`, current demand `D` and other protected funds `R`:

```text
Shortage  = max(0, R + D + F - B)
Preferred = max(0, R + D + H - B)
Bound     = max(0, D + H - B)
Capacity  = max(0, SourceBalance - SourceProtected - SourceFloor)
Cap       = min(Capacity, RemainingRefillDaily, PerRefillLimit)
```

If `Shortage` is zero, the engine does not refill solely to reach the soft target. If the required amount exceeds the bound or cap, it blocks rather than funding an incomplete payment. PAY and REFILL have separate daily counters. The module additionally checks the approved request/destination, per-request refill count and exact balance deltas. [Liquidity engine](../packages/py-core/src/treasurypilot_core/engine/liquidity.py) · [module refill](../contracts/src/TreasuryPilotModule.sol) · [algorithm report](submission/technical-documentation.md).

### 4.2 Scheduling and payment value

`schedule_edf` orders requests by UTC due day, approval sequence and request ID. It simulates up to 30 days, resets daily caps at UTC boundaries, carries balances forward and rechecks cooling, limits and refill. It returns a feasible heuristic result, **not a global optimum certificate**. `schedule_cpsat` exists with a default five-second limit and EDF fallback. Reports should state the actual algorithm, solver status and fallback mode. [EDF scheduler](../packages/py-core/src/treasurypilot_core/engine/scheduler.py) · [CP-SAT](../packages/py-core/src/treasurypilot_core/engine/cpsat.py).

The value model can account for the signed early-payment discount, transaction fee, foregone simple supply interest and late fees from confirmed terms. Valuation cannot increase PAY beyond the signed options. ADR-019 defines B0 as manual/EDF with idle cash, B1 as a deterministic optimizer and B2 as AI plus optimizer. Any comparison needs explicit fee/rate assumptions, inputs and actual algorithms. [Scoring](../packages/py-core/src/treasurypilot_core/engine/scoring.py) · [ADR-019](adr/ADR-019-aave-liquidity-and-payment-options.md).

### 4.3 Reserves, Aave and borrowing proposals

[![Liquidity reserve and Aave decision](report_site/diagrams/liquidity-decision.svg)](report_site/diagrams/liquidity-decision.svg)

*Figure 04.1 — Liquidity decision · [Edit in draw.io](report_site/diagrams/liquidity-decision.drawio).*

```text
RequiredSafeReserve = PaymentReserve + SafeFloor + DebtServiceReserve + ExecutionHolds
AvailableForSupply  = max(0, SafeUSDC - RequiredSafeReserve)
AccessibleLiquidity = SafeUSDC + min(aUSDC, PoolAvailableUSDC)
Deficit             = max(0, RequiredSafeReserve - SafeUSDC)
WithdrawTarget      = ceil(Deficit × 105 / 100)
```

`PaymentReserve` includes approved unpaid obligations within the reserve horizon and chooses the known early amount when applicable. Supply requires a minimum amount and stays within caps. Withdraw is bounded by aToken balance and available pool cash. A remaining deficit becomes an insufficient-liquidity decision, not an automatic borrow. The module enforces a static floor and supply caps; the **dynamic reserve is computed and checked off-chain**. [Liquidity engine](../packages/py-core/src/treasurypilot_core/engine/liquidity.py) · [forecast](../packages/py-core/src/treasurypilot_core/engine/forecast.py) · [Aave contract paths](../contracts/src/TreasuryPilotModule.sol).

## 05 · Policy, mandate and smart contracts

### 5.1 Three-way policy decision

[![Four authorization checks for payment execution](report_site/diagrams/authority-boundaries.svg)](report_site/diagrams/authority-boundaries.svg)

*Figure 05.1 — Authority boundaries · [Edit in draw.io](report_site/diagrams/authority-boundaries.drawio).*

The validator evaluates a chain snapshot, request, policy version, balances, limits, payee and plan/step, then returns `ALLOW`, `NEEDS_APPROVAL` or `BLOCK` with stable reason codes. `NEEDS_APPROVAL` is not executable until an owner grants a precisely scoped exception. Shared Python/Foundry differential vectors compare validator outcomes with contract success or revert selectors for unknown payee, cooling, pause, expiry, caps, duplicate, floor and replay cases. [Validator](../packages/py-core/src/treasurypilot_core/policy/validator.py) · [reason codes](../packages/py-core/src/treasurypilot_core/policy/reason_codes.py) · [differential report](testing/policy-contract-differential-report.md).

### 5.2 Mandate and governance

Safe T owner/threshold governs payees, assets, operational wallets, PAY/REFILL limits, floors, validity, pause/revoke, exceptions, Aave settings and one-time borrow/repay grants. The factory creates one module instance per treasury. Owner or guardian pause affects subsequent module actions only after the pause transaction is mined. It does not undo settled transfers or restrict direct Safe owner actions. [Governance](../contracts/src/TreasuryPilotGovernance.sol) · [factory](../contracts/src/TreasuryPilotModuleFactory.sol) · [mandate API](../services/api/src/treasurypilot_api/mandate/routes.py).

### 5.3 On-chain entry points

| Group | Entry points | Core condition |
|---|---|---|
| Vendor payment | `pay` | Valid approval and amount option, allowed payee, per-request/daily limits, floor, no replay. |
| Internal liquidity | `refill` | Safe T to a registered operational wallet, bounded by request need and refill limits. |
| Idle funds | `supply`, `withdraw` | Fixed pool/asset, floor/caps and exact asset-delta checks; no generic arbitrary execution. |
| P2 debt | `authorizeBorrow`, `authorizeRepay`, `borrow`, `repay` | One-time owner grant with expiry; borrow also checks current rate and health factor. |
| Specialized paths | `swapForGas` and executor wrappers | Environment-specific configuration and evidence are required; code presence does not put all paths in the M1 demo. |

See [TreasuryPilotModule](../contracts/src/TreasuryPilotModule.sol), [PlanAttestedExecutor](../contracts/src/PlanAttestedExecutor.sol), [ReserveHoldExecutor](../contracts/src/ReserveHoldExecutor.sol) and [ThresholdApprovalExecutor](../contracts/src/ThresholdApprovalExecutor.sol).

## 06 · AI agent

### 6.1 AI's role

AI assists with invoice and terms extraction, plan proposals, exception drafts, Copilot answers and anomaly explanations. `worker-ai` calls the model with read-only tools and budget/failover controls. `worker-core` uses the deterministic engine and holds the policy-attestation boundary. The repository includes provider adapters, versioned prompts, an instruction detector, secret scan, read-only tools and evaluation harnesses. [Agent code](../services/worker/src/treasurypilot_worker/agent/) · [AI architecture](AI_AGENT_ARCHITECTURE.md) · [Google Doc AI tab](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.yed8bvlknow6).

### 6.2 Output contract and injection defenses

PDF/email content is untrusted data. Text in a document must not become a mandate or payee change, and a proposed address cannot become executable without confirmation and deterministic validation. The AI receives neither signing keys nor write tools. Its output passes schemas, reference checks and calculations outside the model. Untrusted-content wrappers, secret scans, instruction detection and prompt policy reduce risk; they are not proof of immunity to prompt injection. [Untrusted wrapper](../services/worker/src/treasurypilot_worker/agent/untrusted.py) · [detector](../services/worker/src/treasurypilot_worker/agent/instruction_detector.py) · [secret scan](../services/worker/src/treasurypilot_worker/agent/secret_scan.py).

### 6.3 Bounded evaluation results

| Artifact dated 15 October 2026 | Reported result | Interpretation limit |
|---|---|---|
| [Extraction accuracy](evidence/extraction-accuracy.md) | 30 recorded invoices; amount 27/30; terms F1 70.6%; exact terms 60%. | Labels await second-person review; public/recorded set, not production accuracy. |
| [Copilot fidelity](evidence/copilot-fidelity.md) | 20/20 cases meet numeric-fidelity checks. | AI-authored cases await independent review; not a measure of all real questions. |
| [Red-team](evidence/redteam-results.md) | 0/20 cases changed a field/policy; model flagged 20/20. | Keyword fallback alone flagged 2/20; 20 cases do not establish general injection resistance. |

## 07 · Execution, signer and recovery

### 7.1 Safe execution sequence

Each step needs a stable plan/step ID, fresh state, a policy decision, an attestation bound to plan hash/nonce/expiry, and a PostgreSQL outbox row before broadcast. The signer checks the typed step, attestation, target chain/module and calldata against the plan, simulates with `eth_call`, reserves nonce/step state against duplicates and signs using the executor key. An internal `/sign-and-send` endpoint exists. Older submission text saying the signer has only a health endpoint is stale for this commit. [Signer API](../services/signer/src/treasurypilot_signer/main.py) · [signing service](../services/signer/src/treasurypilot_signer/service.py) · [store](../services/signer/src/treasurypilot_signer/store.py).

### 7.2 Unknown outcomes and partial plans

[![Transaction outcome and recovery flow](report_site/diagrams/execution-recovery.svg)](report_site/diagrams/execution-recovery.svg)

*Figure 07.1 — Outcome recovery · [Edit in draw.io](report_site/diagrams/execution-recovery.drawio).*

After a timeout, the worker must not invent a fresh request/step identity and retry blindly. It checks receipt, nonce, module `requestPaid`/`stepUsed` and actual chain state, blocking or routing the treasury to review until the outcome is known. Confirmed steps in a multi-step plan must not be replayed after a later step fails. Outbox, sequencer, tracker and partial-recovery code exist; full durability must still be demonstrated by environment-specific end-to-end evidence. [Executor](../services/worker/src/treasurypilot_worker/executor/) · [recovery](../services/worker/src/treasurypilot_worker/recovery/) · [risk KR-09](security/known-risks.md).

### 7.3 Circuit breaker and pause

The API and worker include review/circuit-breaker paths, and the internal sentinel service can request pause. “Pause requested” is different from “pause mined”; only mined contract state blocks future module calls, and Safe owners retain their separate authority. [Circuit API](../services/api/src/treasurypilot_api/recovery/circuit.py) · [sentinel](../services/signer/src/treasurypilot_signer/sentinel.py).

## 08 · Data, API and web interface

### 8.1 Data model

PostgreSQL groups identity/org/session, treasury/wallet/chain, mandate/payee/exception, invoice/request/approval, plan/step/AI call, operation/event/snapshot, reconciliation/evidence/audit, notification and administration data. Business tables carry an organization scope; amounts are integer base units. Migrations are the source for the current schema; [DATA_MODEL](DATA_MODEL.md) is the design overview. [Migrations](../services/api/migrations/versions/) · [Google Doc data-model tab](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.py8ti27c4ma4).

The minimum evidence chain is request → invoice hash/fingerprint → typed approval/signature → plan/policy version → operation/step ID → transaction hash/receipt/events → verification → reconciliation → audit/evidence bundle. A transaction hash alone is not a complete payment explanation. [Audit models](../services/api/src/treasurypilot_api/audit/models.py) · [reconciliation models](../services/api/src/treasurypilot_api/reconciliation/models.py).

### 8.2 API surface

| Domain | Example capability | Implementation |
|---|---|---|
| Identity | Auth, organization, membership, MFA, OIDC/SAML/SCIM | [Router wiring](../services/api/src/treasurypilot_api/main.py), [identity](../services/api/src/treasurypilot_api/identity/) |
| Treasury | Chain, treasury, Safe, forecast, snapshot | [Treasury API](../services/api/src/treasurypilot_api/treasury/api.py), [forecast](../services/api/src/treasurypilot_api/treasury/forecast.py) |
| Mandate | Payee, governance transaction, pause, exception, fee policy | [Mandate](../services/api/src/treasurypilot_api/mandate/) |
| Requests | Intake/upload, terms, EIP-712 approval, cancel | [Requests](../services/api/src/treasurypilot_api/invoices/requests.py) |
| Execution | Plan/operation sequencing and status | [Execution](../services/api/src/treasurypilot_api/execution/routes.py) |
| Evidence | Reconciliation, export, audit log, verification | [Reconciliation](../services/api/src/treasurypilot_api/reconciliation/), [audit](../services/api/src/treasurypilot_api/audit/) |
| Support | Notification, webhook, Copilot, ERP adapter | [Notifications](../services/api/src/treasurypilot_api/notifications/), [Copilot](../services/api/src/treasurypilot_api/copilot/api.py), [ERP](../services/api/src/treasurypilot_api/integrations/erp/) |

Major routes use `/v1` and organization-scoped routes include the organization ID. [API_SPEC](API_SPEC.md) can lag or lead code, so integrations should compare generated OpenAPI with the [web client schema](../apps/web/openapi.json). The React/Vite UI includes setup, dashboard, requests, approval, plans, review, mandate, payees, reconciliation, metrics and Copilot. [Web app](../apps/web/src/app.tsx) · [package](../apps/web/package.json).

## 09 · Chain evidence and reconciliation

The chain reader/indexer creates snapshots and follows events and receipts. Verification checks postconditions before declaring a payment result. Reconciliation distinguishes internal refill/swap from vendor expense and supports match, discrepancy and resolve flows. Audit logs, evidence bundles and EAS helpers add traceability, but invoice/approval/plan hashes inside EAS are backend assertions. An auditor must check the trusted attester, schema and actual PAY transaction. [Chain worker](../services/worker/src/treasurypilot_worker/chain/) · [verifier](../services/worker/src/treasurypilot_worker/reconcile/verify.py) · [reconciliation routes](../services/api/src/treasurypilot_api/reconciliation/routes.py) · [receipt helper](../infra/scripts/attest_receipt.py).

The current [Sepolia manifest](../deployments/11155111.json) says `deploymentStatus: deployed` and contains the module, Safe T/O1, code hashes and verification block. This is a deployment artifact with addresses and checks; it does **not alone prove** that all public demo/reconciliation scenarios succeeded. The [15 October reliability report](evidence/reliability-2026-10-15.md) records 30/30 completed local Anvil runs and zero Sepolia runs. Some older submission drafts still say `configured_only`; each claim needs its own revision/date.

## 10 · Security and compliance

### 10.1 Primary controls

- The module rejects unapproved recipients, excess limits, floor breaches, expiry, pause/revoke, replay and a payment amount outside the signed option. [Contract](../contracts/src/TreasuryPilotModule.sol).
- The signer isolates the executor key and checks attestation, payload and simulation. Compose does not pass policy/executor signing secrets to the AI worker. [Signer](../services/signer/src/treasurypilot_signer/) · [Compose](../infra/compose.yaml).
- Identity/RBAC and scoped repositories enforce multi-tenant access; maker-checker adds a separate business rule. [RBAC](../services/api/src/treasurypilot_api/identity/rbac.py) · [scoped repository](../services/api/src/treasurypilot_api/common/repository.py).
- Screening, KYB, travel-rule and data-region code exist, but fixture screening is not evidence of live provider coverage or legal approval. [Compliance](../services/api/src/treasurypilot_api/compliance/) · [risk KR-19](security/known-risks.md).
- Privacy classification, redaction and encryption primitives must be applied by each integration, log path and export. [Privacy package](../packages/py-core/src/treasurypilot_core/privacy/).

### 10.2 Open risks for public claims

The contracts lack an independent audit. Other Safe owners/modules can move funds outside the mandate. RPC failures and reorgs affect finality. Dynamic reserves are not fully enforced on-chain. Aave pool caps and liquidity change. Signer database privilege needs hardening. Invoice data can be exposed or misread. Fixture sanctions checks are not live coverage. A single Compose VM is a concentrated failure point. The full register and severity context are in [known risks](security/known-risks.md) and the [security self-assessment](submission/security-self-assessment.md).

## 11 · Testing, metrics and reproducibility

| Layer | Code or evidence | What it establishes |
|---|---|---|
| Unit/property | [py-core tests](../packages/py-core/tests/), [API tests](../services/api/tests/) | Defined cases and invariants, not end-to-end operation. |
| Contract | [Foundry tests](../contracts/test/), [test evidence](security/test-evidence.md) | Module behavior in specified test/fork revisions. |
| Policy ↔ contract | [Differential matrix](testing/policy-contract-differential-report.md) | Agreement over shared vectors, with documented uncovered cases. |
| Web | [Vitest/Playwright](../apps/web/e2e/) | UI behavior under its fixture/mock setup. |
| AI | [Extraction](evidence/extraction-accuracy.md), [Copilot](evidence/copilot-fidelity.md), [red-team](evidence/redteam-results.md) | Bounded recorded/synthetic results, not general production quality. |
| Reliability | [30-run Anvil report](evidence/reliability-2026-10-15.md) | 30/30 local scenario runs; no Sepolia run in that report. |

A reproducible benchmark must record SHA, chain ID/block, asset/decimals, dataset split and exposure, model/prompt, actual EDF/CP-SAT/fallback path, fee/rate assumptions, denominators and failures. Anvil, historical fork and public Sepolia results must be reported separately. [Submission evaluation protocol](submission/technical-documentation.md) · [planner benchmark](../services/worker/src/treasurypilot_worker/planner_bench/).

## 12 · Deployment and operations

### 12.1 Environments

Local Compose starts PostgreSQL 16, Redis 7, MinIO, optional Anvil, migrations, API, core/AI/webhook workers, beat, signer and web. Sepolia has a separate override and deployment manifest/scripts. Before a demo, check chain ID, RPC, Safe owners/threshold/module enablement, token decimals, mandate expiry, payees, pool/aToken, gas and EAS attester. Aave supply headroom can differ from a historical fork. [Infra README](../infra/README.md) · [Compose](../infra/compose.yaml) · [Sepolia override](../infra/compose.sepolia.yaml) · [deployment guide](../contracts/docs/DEPLOYMENT.md).

### 12.2 Observability and incidents

The stack includes correlation IDs, metrics/tracing, Sentry/OpenTelemetry and notification outboxes. An incident record should identify request/plan/operation IDs, policy reason code, chain/block, tx/nonce/receipt and the retry or review decision. Logs and exports should omit raw keys, session tokens, signatures and sensitive invoice content. [Core observability](../packages/py-core/src/treasurypilot_core/observability.py) · [metrics](../services/api/src/treasurypilot_api/observability/metrics.py) · [notifications](../services/worker/src/treasurypilot_worker/notify/).

## 13 · Implementation status and gaps

| Area | Observed at commit `50b1117` | Needed for a stronger completion claim |
|---|---|---|
| Web/API | Many screens, endpoints and migrations are present. | Run demo-configuration end-to-end tests and check OpenAPI/client alignment. |
| Engine/policy | EDF, CP-SAT, forecast, liquidity and validator have code/tests. | Publish correctly labeled B0/B1/B2 measurements on reviewed held-out data. |
| Contract/chain | Module entry points and a Sepolia manifest marked `deployed`. | Public transaction evidence for each claimed demo scene, independent authorization review and audit before mainnet. |
| Signer/worker | `/sign-and-send`, outbox, sequencing and recovery code exist. | Restart/reorg/partial-step tests on testnet and signer DB privilege review. |
| AI | Extraction/Copilot/guard code and recorded evaluations exist. | Independent ground truth, protected held-out cases and broader OCR/injection/locale evaluation. |
| Reliability | The 15 October report records 30/30 Anvil runs. | Separate Sepolia evidence and backup/restore exercises. |

These are **verification requests**, not claims that the implementation is absent. Source code supports statements about individual components and boundaries; production readiness needs a release-specific system and security review. [Submission README](submission/README.md) · [known risks](security/known-risks.md).

## 14 · Module map and implementation dependencies

The Google Doc organizes the project into M01–M20. Its assignment tab reflects the team plan **as of 11–12 October 2026**, not the current issue state. This map points readers to the technical ownership area for each module. [Module catalog](modules/README.md) · [assignment tab](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.3xlngx2j9mze).

| Module | Responsibility | Entry point |
|---|---|---|
| M01 Identity | Session, SIWE, organizations, RBAC, MFA/federation | [identity](../services/api/src/treasurypilot_api/identity/) |
| M02 Treasury | Safes, wallets, chain, snapshots, forecast | [treasury API](../services/api/src/treasurypilot_api/treasury/) |
| M03 Mandate | Payees, caps, governance, exceptions and pause | [mandate API](../services/api/src/treasurypilot_api/mandate/) |
| M04 Contracts | Module/factory, EIP-712, Aave, replay and floors | [contracts](../contracts/src/) |
| M05 Invoices | Intake, extraction, requests and approval | [invoices](../services/api/src/treasurypilot_api/invoices/) |
| M06 Chain reader | RPC, indexer, tracker and snapshot | [chain worker](../services/worker/src/treasurypilot_worker/chain/) |
| M07 Financial engine | Refill, EDF/CP-SAT, reserve and forecast | [engine](../packages/py-core/src/treasurypilot_core/engine/) |
| M08 Policy | Validator, reason codes and attestation | [policy](../packages/py-core/src/treasurypilot_core/policy/) |
| M09 Agent | Extraction, proposals, Copilot and evaluation | [agent](../services/worker/src/treasurypilot_worker/agent/) |
| M10 Execution | Outbox, sequencing, signing and simulation | [executor](../services/worker/src/treasurypilot_worker/executor/), [signer](../services/signer/src/treasurypilot_signer/) |
| M11 Reconciliation | Receipts, verification, match and export | [worker](../services/worker/src/treasurypilot_worker/reconcile/), [API](../services/api/src/treasurypilot_api/reconciliation/) |
| M12 Recovery | Unknown/partial state, retry and review | [worker](../services/worker/src/treasurypilot_worker/recovery/), [API](../services/api/src/treasurypilot_api/recovery/) |
| M13 Notifications | In-app, webhook, email and Telegram | [notify worker](../services/worker/src/treasurypilot_worker/notify/) |
| M14 Compliance | Screening, KYB, travel rule and retention | [compliance](../services/api/src/treasurypilot_api/compliance/) |
| M15 Audit | Log, hash chain and evidence bundle | [audit](../services/api/src/treasurypilot_api/audit/) |
| M16 Web | Operator, approver and owner interface | [features](../apps/web/src/features/) |
| M17 Observability | Metrics, savings, logs and traces | [observability](../services/api/src/treasurypilot_api/observability/) |
| M18 Platform admin | Multi-organization operations support | [admin](../services/api/src/treasurypilot_api/admin/) |
| M19 DevEx | Build, Compose, CI, tests and OpenAPI | [infra](../infra/), [workflows](../.github/workflows/) |
| M20 Domain/evidence | Demo scenarios, measurement and business review | [evidence](evidence/), [submission](submission/) |

**Dependency chain:** contract ABI/EIP-712 and chain snapshots shape the validator; validator and engine shape the attested plan; signer/executor accept only checked steps; tracker/verifier enable Paid and reconciliation; web and AI consume these data contracts. The assignment tab's streams A (chain/engine/policy/execution/recovery), B (product/API/web/AI) and C (business/evidence) reflect this order. Use current code, PRs and project state instead of the tab's historical ticket counts for a new sprint.

## 15 · Sources and maintenance

| Topic | Primary source |
|---|---|
| Product and scope | [Google Doc](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit), [PROJECT_OVERVIEW](PROJECT_OVERVIEW.md) |
| Architecture and trust | [SYSTEM_ARCHITECTURE](SYSTEM_ARCHITECTURE.md), [entry overview](../ARCHITECTURE.md) |
| Financial and authorization rules | [BUSINESS_RULES](BUSINESS_RULES.md), [contracts](../contracts/src/), [policy](../packages/py-core/src/treasurypilot_core/policy/) |
| Data and API | [DATA_MODEL](DATA_MODEL.md), [API_SPEC](API_SPEC.md), [migrations](../services/api/migrations/versions/) |
| AI | [AI_AGENT_ARCHITECTURE](AI_AGENT_ARCHITECTURE.md), [agent code](../services/worker/src/treasurypilot_worker/agent/) |
| Version 0.3 decisions | [ADR-019](adr/ADR-019-aave-liquidity-and-payment-options.md), [Google Doc tab 37](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit?tab=t.85x0bmmbqru0) |
| Operations, tests and risks | [infra](../infra/), [evidence](evidence/), [security](security/), [submission](submission/) |

**Update rule:** record a new commit and date; compare routes, schema and contracts with source; rerun evaluations with revision-bound artifacts; verify the manifest against chain state at the recorded block; separately label “code present,” “local test,” “public transaction” and “independent audit.” This Markdown is the editable source for the English documentation pages.
