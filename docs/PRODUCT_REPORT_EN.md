# TreasuryPilot — Product & Technical Report

**Audience:** project reviewers, technical collaborators and prospective partners

**Reviewed:** 16 October 2026 · **Code baseline:** `50b1117`

**Scope:** repository implementation, dated local/fork evidence, Sepolia deployment manifest and the [TreasuryPilot project document](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit). This report distinguishes code, test results, deployment configuration and future work. It is not a production security audit.

> **Executive summary.** TreasuryPilot coordinates stablecoin invoice payments across an organization's Safe wallets. A human confirms and signs the payment obligation; AI extracts and explains information; a deterministic engine plans liquidity and timing; policy, an isolated signer and an on-chain module constrain execution. The repository contains substantial implementations and local evidence. Public Sepolia end-to-end results and independent security review remain separate verification steps.

## 1. Target Users & Current Journey

### Who is TreasuryPilot for?

The primary users are finance and treasury operators who receive invoices and manage cash across wallets; payment approvers who decide whether a specific obligation may be paid; and treasury owners who configure payees, limits, operational wallets and emergency controls. A compliance or audit reviewer consumes the resulting evidence rather than initiating a payment. The product assumes an organization already uses stablecoins and Safe-based custody; it is not a consumer wallet or a general-purpose trading agent. [Product overview](PROJECT_OVERVIEW.md) · [identity/RBAC](../services/api/src/treasurypilot_api/identity/).

### How are invoices and stablecoin payments handled today?

The following current journey is a **workflow reconstruction from the project brief and implementation**, not an independently measured user-research finding. An operator receives an invoice as a PDF, email or ERP record; reads the payee, amount, asset and due date; checks it against the vendor record; requests approval; checks which Safe holds the required token and gas; moves liquidity if the operational Safe is short; submits a transaction; then records a hash, receipt and accounting match. The approval, liquidity move and proof often live in different systems. TreasuryPilot's source materials describe this fragmentation as the problem to address. [Project overview](PROJECT_OVERVIEW.md) · [system architecture](SYSTEM_ARCHITECTURE.md).

### What are the main steps and tools?

| Step | Typical action in the reconstructed journey | Tools or records involved |
|---|---|---|
| Intake | Receive and read invoice, terms and vendor address. | Email/PDF, spreadsheet or ERP, document storage. |
| Authorization | Confirm the obligation and obtain a second person's approval. | Internal workflow, wallet signature, vendor record. |
| Funding | Check balances and transfer stablecoins or gas between treasury and operating wallets. | Safe UI, RPC/block explorer, token wallet. |
| Settlement | Submit the vendor payment and wait for confirmation. | Safe/module transaction, signer, chain RPC. |
| Evidence | Match payment to invoice and explain any discrepancy. | Transaction receipt, explorer, accounting or reconciliation system. |

This table describes the problem workflow, not a claim that every TreasuryPilot customer currently uses the same tools. The implemented product replaces manual joins between those records with request IDs, hashes, policy decisions, outbox steps and reconciliation links. [Invoice routes](../services/api/src/treasurypilot_api/invoices/requests.py) · [reconciliation](../services/api/src/treasurypilot_api/reconciliation/).

## 2. Pain Points & Solution Directions

### Four material pain points

| Pain point | Consequence | Gap in a manual or generic-wallet workflow | TreasuryPilot direction |
|---|---|---|---|
| Approved invoice, wrong wallet balance | Payment is late even when the organization owns enough stablecoins elsewhere; emergency top-ups create extra work. | A wallet balance view does not reserve funds for signed, due obligations or enforce request-bound refill. | Compute a fresh shortage and reserve; refill only to a registered operating Safe, within mandate and daily/per-request limits. |
| Approval is detached from the exact transfer | A changed payee, asset, amount or deadline can turn a business approval into a different payment. | A database `approved` flag or chat message is not a cryptographic on-chain authorization. | Human signs EIP-712 fields for the exact obligation; module checks the active approver, amount option and replay state. |
| Automation can exceed safe limits | A compromised executor, stale plan or faulty AI recommendation could spend beyond intended scope. | A generic hot wallet has broad signing authority; off-chain simulations can become stale. | Deterministic policy and attestation, isolated signer, latest-state simulation and module-enforced payee, caps, floor, expiry and pause. |
| Proof and recovery are fragmented | Teams cannot easily prove what was approved, what was sent or whether a timed-out operation succeeded. | A transaction hash alone omits invoice, approval, policy version and postcondition. | Persist outbox and stable step IDs before broadcast; verify receipts and state; reconcile against the request and export an evidence bundle. |

The four directions are implemented to different levels. The code contains the principal components, but a complete operational claim needs a release-specific end-to-end run, public transaction evidence where claimed, and an independent control review. AI helps with document interpretation; it does not replace these controls. [Liquidity engine](../packages/py-core/src/treasurypilot_core/engine/liquidity.py) · [contract](../contracts/src/TreasuryPilotModule.sol) · [outbox](../services/worker/src/treasurypilot_worker/executor/outbox.py) · [known risks](security/known-risks.md).

## 3. MVP Scope & Current Coverage

### What the MVP focuses on

M1 focuses on a bounded stablecoin invoice payment: one organization's treasury Safe T, an operational Safe O1, an allowed vendor, a signed payment obligation, request-bound internal refill when needed, constrained module execution, and a linked receipt/reconciliation record. The working evaluation context is synthetic assets on Ethereum Sepolia and local Anvil/fork setups. Local fixtures may include O2, but the Sepolia demo manifest records one operational wallet. [Scope decisions](vi/37-cap-nhat-v03.md) · [Sepolia manifest](../deployments/11155111.json).

### What is implemented or locally evidenced?

Invoice intake, human confirmation and approval endpoints; a typed EIP-712 payment structure; policy validation; integer-money liquidity and EDF scheduling; CP-SAT code with EDF fallback; outbox/sequencer/recovery paths; an isolated `/sign-and-send` service; Safe/module contracts; chain tracking, reconciliation and evidence functions are present in the repository. Foundry, Python, UI and AI test suites provide bounded evidence. The 15 October reliability artifact records 30/30 local Anvil runs for `demo-main`; it records **zero Sepolia runs**. [Technical report](TECHNICAL_REPORT_EN.md) · [reliability report](evidence/reliability-2026-10-15.md).

### What remains outside a validated MVP claim?

The deployment manifest says `deployed` and contains addresses and code hashes, but it is not a catalog of successful public PAY transaction hashes. Aave supply depends on live pool headroom; a historical USDC fork case found a full cap at block 11,890,000. Borrow/repay functions require a one-time owner grant and are P2 contract capabilities, not autonomous M1 borrowing. Mainnet production use, an independent contract audit, live sanctions/KYB coverage and a statistically representative AI accuracy claim are outside the verified scope. Some endpoints and adapters exist without proof that external providers are configured in a given environment. [Contract security evidence](security/test-evidence.md) · [known risks](security/known-risks.md).

## 4. Introducing TreasuryPilot

### What is it?

TreasuryPilot is a controlled orchestration layer for invoice-to-stablecoin payment. It joins the business object (the invoice and approved request), the cash decision (when and from which Safe to pay), the execution authority (signer and constrained module), and the evidence trail (receipt, chain state and reconciliation). It is designed around an organization's existing Safe custody rather than handing unrestricted funds to an agent. [Architecture](SYSTEM_ARCHITECTURE.md) · [module](../contracts/src/TreasuryPilotModule.sol).

### How are Human, AI and Smart Contract responsibilities divided?

| Participant | Decides or produces | Cannot do alone |
|---|---|---|
| Human operator | Confirms invoice fields and submits a request. | Authorize an unreviewed payment if maker-checker applies. |
| Human approver | Signs the exact EIP-712 payment obligation. | Change the treasury mandate with that invoice signature. |
| Safe owner / guardian | Owner governs mandate, exceptions and resume; owner or guardian can pause. | Retroactively undo a settled transfer. |
| AI worker | Extracts terms, drafts explanations and suggests options using read-only tools. | Sign, change payee/limits or create spending authority. |
| Deterministic engine + policy | Compute feasible timing/liquidity and return `ALLOW`, `NEEDS_APPROVAL` or `BLOCK`. | Replace the human approval or bypass the contract. |
| Signer + module | Verify typed execution, simulate, sign and recheck limits on-chain. | Widen the mandate or silently pay an arbitrary address. |

The main distinction is the linked, layered evidence: a payment must be traceable from the invoice and human signature through a versioned policy decision to an actual chain effect. “AI-powered” describes assistance with information and options, not autonomous control of company funds. [AI architecture](AI_AGENT_ARCHITECTURE.md) · [governance](../contracts/src/TreasuryPilotGovernance.sol).

## 5. How TreasuryPilot Works

### Invoice-to-payment sequence

1. An operator creates or imports an invoice request. The backend stores the document privately, normalizes fields and terms, checks fingerprints and flags suspicious content.
2. A human confirms important fields. Backend roles and maker-checker rules gate submission. The approver retrieves typed EIP-712 data and signs the exact payee, asset, amount options, deadlines and request identity.
3. The worker reads a fresh chain snapshot and unpaid obligations. The deterministic engine computes shortages, reserves and a payment schedule. AI may provide a proposal or explanation, but the engine recalculates amounts in integer base units.
4. Policy validates the request and plan against the mandate, approved payee, caps, floors, cooling rules and current state. `ALLOW` can continue. `NEEDS_APPROVAL` waits for a precisely scoped owner exception. `BLOCK` stops execution.
5. The system writes stable plan/step and outbox records before broadcast. The signer verifies the attested typed step and calldata, simulates with `eth_call`, controls nonce reuse and submits through the module. The module checks authorization and current limits again at execution time.
6. The tracker waits for receipt and sufficient chain confirmation. The verifier checks expected balance and request state changes; reconciliation links the vendor payment to the invoice and separates any internal refill from spend. Audit/evidence records the result.

**When is payment automatic?** Only after a human-approved obligation exists, policy returns an executable decision, required liquidity and gas are available, the signer accepts the current step, and the module's on-chain checks pass. This is automatic execution of an approved and bounded request, not automatic approval by AI. **When is human intervention required?** A missing or changed approval, `NEEDS_APPROVAL`, high-risk flags, insufficient liquidity, a pause, or an unresolved unknown outcome routes to review. [Request state machine](../services/api/src/treasurypilot_api/invoices/state_machine.py) · [validator](../packages/py-core/src/treasurypilot_core/policy/validator.py) · [executor](../services/worker/src/treasurypilot_worker/executor/).

**What happens after a timeout?** A timeout is an unknown state, not a failure. The worker checks the receipt, nonce, `requestPaid`/`stepUsed` and actual chain effects before any retry. Confirmed steps in a multi-step plan remain consumed even if a later step fails. The repository implements outbox, tracking and partial recovery paths; release-specific restart/reorg E2E evidence is still needed. [Recovery](../services/worker/src/treasurypilot_worker/recovery/) · [risk KR-09](security/known-risks.md).

## 6. High-Level System Architecture

### 6.1 Overall Architecture

The deployment has four operational zones. The **application zone** is a React/Vite browser interface plus connected wallet. The **business zone** is FastAPI, PostgreSQL and Redis/Celery, which persist requests and dispatch asynchronous work. The **decision and execution zone** separates `worker-ai`, `worker-core`/`py-core` and the isolated signer. The **chain zone** contains TreasuryPilotModule, Safe T/O1, assets and optional Aave/EAS integrations. A chain reader/tracker brings balances, events and receipts back to the backend. [Compose topology](../infra/compose.yaml) · [architecture report](TECHNICAL_REPORT_EN.md).

A typical user request travels browser → API → PostgreSQL/outbox → worker core → policy → signer → chain RPC → module/Safes. Receipt and event observations travel back through tracker/verifier → reconciliation/API → frontend. Redis transports work but is not a source of payment truth; PostgreSQL is the business record, and chain state is the final authority for a mined transfer. AI is an advisory branch from the API/worker pipeline. It has read-only tools and does not sit on the signing path. [Worker tasks](../services/worker/src/treasurypilot_worker/tasks.py) · [chain worker](../services/worker/src/treasurypilot_worker/chain/).

### 6.2 Frontend

The frontend serves operators, approvers, owners and reviewers through setup, dashboard, request, approval, plan, review, mandate, payee, reconciliation, metrics and Copilot screens. It routes the user to role-appropriate actions, calls organization-scoped `/v1` APIs, shows current request and operation state, and asks the connected wallet to sign typed EIP-712 data or Safe governance transactions. The web package uses **React 18, TypeScript, Vite, React Router, TanStack Query, wagmi and viem**. The wallet signs; it does not compute policy or decide the amount to broadcast. [Web app](../apps/web/src/app.tsx) · [web dependencies](../apps/web/package.json) · [features](../apps/web/src/features/).

The browser is an untrusted client. API session and RBAC checks must bind every request to the correct organization; the module still checks payment authorization on-chain. UI confirmation screens help users review a payee and amount, but their presence cannot substitute for a valid signature and contract validation. [Identity](../services/api/src/treasurypilot_api/identity/) · [approval API](../services/api/src/treasurypilot_api/invoices/approval.py).

### 6.3 Backend & Core Services

| Component | Principal input | Processing and output |
|---|---|---|
| FastAPI | Session, organization scope, invoices, approvals and user actions | Auth/RBAC, validation, persistence, typed data, plan/execution and evidence APIs. |
| PostgreSQL | Business writes from API and workers | Durable requests, approvals, plans, operations/outbox, audit and reconciliation state. |
| Redis/Celery | Scheduled or queued work | Dispatch between workers; it is not the payment ledger. |
| Worker AI | Invoice text, read-only context and prompt configuration | Structured extraction, proposals and explanations; no keys or write authority. |
| Worker Core + py-core | Signed obligation, fresh chain snapshot, balances, mandate and obligations | Integer-money calculations, EDF/CP-SAT scheduling, reserve decisions, policy reasons and attested steps. |
| Isolated signer | Exact typed step, attestation, target chain/module and calldata | Verify, simulate current state, reserve nonce/step identity and sign/send. |
| Chain tracker/verifier | RPC balances, events, receipt and confirmations | Confirm postconditions and feed reconciliation/evidence. |

The API and workers are Python services. FastAPI handles HTTP; Celery/Redis dispatch background tasks; PostgreSQL stores business state. `py-core` intentionally contains deterministic money, scheduling and policy logic that can be tested without a model call. The signer is a separate service because private-key use has a different trust boundary from document parsing. [API main](../services/api/src/treasurypilot_api/main.py) · [core package](../packages/py-core/src/treasurypilot_core/) · [signer service](../services/signer/src/treasurypilot_signer/service.py).

### 6.4 Data & Blockchain Layer

**Off-chain:** invoices and private documents, organization/member records, role assignments, signatures, requests, AI outputs, plans, outbox and audit/reconciliation records reside in services and PostgreSQL; Redis carries task messages. Sensitive documents are not made public merely to prove a payment. Amounts use integer base units and timestamps use UTC rules. [Data model](DATA_MODEL.md) · [migrations](../services/api/migrations/versions/) · [money type](../packages/py-core/src/treasurypilot_core/money/base_units.py).

**On-chain:** Safe T owns treasury funds and the mandate; Safe O1 is an operational payer. TreasuryPilotModule checks the active approver's EIP-712 signature and option, allowed payee, current policy configuration, per-request and daily caps, hard floor, pause/revoke, expiry and replay state. Aave interactions use a fixed pool/asset and related caps; the dynamic reserve remains an off-chain calculation. EAS can carry a receipt assertion, which must be checked against the actual PAY transaction and trusted attester. [Module](../contracts/src/TreasuryPilotModule.sol) · [governance](../contracts/src/TreasuryPilotGovernance.sol) · [EAS helper](../infra/scripts/attest_receipt.py).

Workers and signer connect through chain RPC for simulation, transaction submission and observation. A chain ID mismatch, stale RPC or reorganization can invalidate an interim conclusion; the system must wait for configured confirmations and reconcile actual state. The Sepolia manifest fixes addresses and a verification block for the reviewed environment but does not itself provide public payment transaction results. [Sepolia manifest](../deployments/11155111.json) · [known risks](security/known-risks.md).

### 6.5 Flow Data

| Moment | Data created or checked | Persistence and authority |
|---|---|---|
| Invoice intake | Original document, extracted fields, terms, fingerprint, anomaly flags. | Private storage and request tables; human checks material fields. |
| Approval | EIP-712 typed fields and human signature. | Approval record and signature; contract later verifies the signer and exact obligation. |
| Planning | Snapshot, unpaid requests, integer balances, reserve, schedule and policy reason. | Plan/version and step IDs in PostgreSQL; AI suggestions remain advisory. |
| Execution preparation | Attestation, calldata, outbox and stable nonce/step identity. | PostgreSQL write precedes broadcast; signer checks fresh state. |
| Chain submission | Signed transaction to module/Safes via RPC. | On-chain state, events and transaction hash; contract rechecks limits. |
| Post-payment | Receipt, confirmations, balance deltas and request-paid state. | Tracker/verifier and reconciliation persist evidence; API returns status to UI. |

The key crossing is **from human intent to executable calldata**. Neither an AI summary nor a database status flag can skip the typed signature, deterministic policy, signer checks and contract checks. [Audit models](../services/api/src/treasurypilot_api/audit/models.py) · [reconciliation models](../services/api/src/treasurypilot_api/reconciliation/models.py).

## 7. AI & Core Logic: Why Both AI and an Engine?

| Decision component | Inputs | Output | Authority boundary |
|---|---|---|---|
| AI | Untrusted invoice text, selected read-only context and prompt/tool schemas. | Candidate fields, terms, explanations or plan suggestions. | No write tool, policy key, executor key or payment signature. |
| Deterministic financial engine | Confirmed obligations, integer balances, deadlines, limits, reserve and fee/rate assumptions. | Feasible refill/withdraw/payment timing and scored options. | Cannot exceed signed payment options or mandate. |
| EDF / CP-SAT scheduler | Due dates, approval order, balance/cap trajectory and time budget. | EDF feasible heuristic or CP-SAT result with fallback/status. | Must report actual algorithm used; no global-optimum claim from EDF. |
| Policy validator | Plan/step, current mandate and chain snapshot. | `ALLOW`, `NEEDS_APPROVAL` or `BLOCK` plus reason codes and attestation boundary. | A block is not executable; owner-scoped exception is needed for review cases. |

LLMs are useful for ambiguous text and natural-language explanation, but they should not be the calculator of record for base-unit amounts, daily counters or feasible schedules. They can misread locale formats, omit terms or follow malicious instructions embedded in a document. The recorded extraction evaluation found amount exact in 27/30 cases and terms F1 70.6%; the red-team fallback keyword detector alone flagged 2/20 cases. These are direct reasons to require human confirmation and deterministic recalculation. [Extraction evaluation](evidence/extraction-accuracy.md) · [red-team evaluation](evidence/redteam-results.md).

The engine prioritizes meeting approved due dates, preserving protected balances and hard floors, and obeying payment/refill caps before considering yield or a signed early-payment discount. `schedule_edf` is a deterministic fallback if CP-SAT is unavailable or times out; `worker-core` can continue on confirmed structured inputs when the model is down. AI extraction failure does not permit silent guessing: fields must be provided or confirmed by a human. The model's proposal is validated against schema, references, current state, signatures and policy before it can influence an execution plan. [EDF scheduler](../packages/py-core/src/treasurypilot_core/engine/scheduler.py) · [CP-SAT](../packages/py-core/src/treasurypilot_core/engine/cpsat.py) · [AI guards](../services/worker/src/treasurypilot_worker/agent/).

## 8. Security and Permission Design

### Roles, approval and custody

Role-based access separates operators, approvers, owners and reviewers. Maker-checker can prohibit a creator from approving their own request; a controlled solo mode has separate rules. Safe T owner/threshold governs mandate and exceptions. A guardian can pause, while resuming an effective on-chain pause is owner-only. A Safe owner or another enabled Safe module can still transact outside the TreasuryPilotModule path, so the mandate must not be described as controlling every possible Safe action. [RBAC](../services/api/src/treasurypilot_api/identity/rbac.py) · [maker-checker](../services/api/src/treasurypilot_api/identity/maker_checker.py) · [pause API](../services/api/src/treasurypilot_api/mandate/pause.py).

### Exact authorization and defense in depth

The `PaymentApproval` EIP-712 structure binds request and invoice identifiers/hashes, treasury, paying wallet, asset, payee, standard and optional early amount/deadline, terms hash, expiry and fiat flag. The domain binds chain and module. A changed signed field invalidates the signature. The signer validates a versioned policy attestation and exact calldata, calls `eth_call` against current state and guards nonce/step reuse. The module checks the active approver (EOA/ERC-1271), approved payee, limits, floor, pause/revoke, expiry and replay protection at execution time. Simulation is a preflight check, not a guarantee that future block state cannot change. [Approval hash](../contracts/src/libraries/PaymentApprovalHash.sol) · [signer](../services/signer/src/treasurypilot_signer/service.py) · [module](../contracts/src/TreasuryPilotModule.sol).

Duplicate payment is addressed at multiple layers: fingerprint and near-duplicate invoice checks, stable request/step IDs, outbox uniqueness/nonce controls, and the module's `requestPaid`/`stepUsed` state. After a timeout, the prior attempt must be reconciled before any new broadcast. These controls reduce accidental replay but still require environment-specific failure/reorg tests. [Fingerprint](../packages/py-core/src/treasurypilot_core/fingerprint/invoice.py) · [outbox](../services/worker/src/treasurypilot_worker/executor/outbox.py) · [recovery](../services/worker/src/treasurypilot_worker/recovery/).

### Compromise boundaries, pause and audit

A compromised AI worker can generate bad suggestions or leak accessible data; it should not have policy/executor signing secrets or write tools. A compromised executor key is constrained by the module's active mandate, approver signature, payee list, caps, floor and replay checks, but it may still cause damage inside those limits; key isolation and monitoring remain necessary. Backend/API compromise, signer/database privileges and direct Safe owner authority are separate risks that the module cannot eliminate. [Compose](../infra/compose.yaml) · [known risks](security/known-risks.md).

Circuit-breaker/review paths in API and worker can stop new operations on suspicious conditions. An owner or configured guardian can request pause; the backend flag may stop work immediately, while on-chain protection is effective only after the pause transaction is mined. Only the owner may resume a mined pause, with governance checks. A pause cannot reverse settled transfers. Audit data links request, invoice hash/fingerprint, approval, plan/policy version, operation/step ID, transaction, receipt, verification and reconciliation; export paths must avoid raw secrets and sensitive invoice contents. [Circuit API](../services/api/src/treasurypilot_api/recovery/circuit.py) · [governance](../contracts/src/TreasuryPilotGovernance.sol) · [audit](../services/api/src/treasurypilot_api/audit/).

### Remaining risk

There is no independent contract audit in the reviewed evidence. Live provider compliance checks, public testnet end-to-end runs, restart/reorg durability, signer DB privilege separation, Aave headroom, RPC quality, document privacy and other Safe modules/owners need release-specific attention. The security design is a set of layered constraints, not proof of zero loss under every compromise. [Known risks](security/known-risks.md) · [self-assessment](submission/security-self-assessment.md).

## 9. Results & Closing

### Implemented capabilities and dated evidence

| Evidence | Result and environment | Practical limit |
|---|---|---|
| Local reliability, 15 Oct 2026 | 30/30 completed `demo-main` runs on Anvil; median `refill_then_pay` 469.4 ms. | This report requested 0 Sepolia runs and does not measure public-chain reliability. |
| Contract campaign, 12 Oct 2026 | 86 Foundry tests passed; 16 invariants with 10,000 runs and depth 32; seven historical Sepolia Aave fork tests passed. | Local/fork evidence with pinned code and blocks, not a live mainnet audit. |
| Python campaign in security evidence | 87 tests passed; reported core coverage 93%. | Scope is the specified Python cases, not full system E2E. |
| Invoice extraction, 15 Oct 2026 | 30 recorded invoices; amount exact 27/30; payment terms F1 70.6%; exact terms 60%. | Labels await second-person review; not production accuracy. |
| Copilot, 15 Oct 2026 | 20/20 recorded cases passed numeric-fidelity checks. | AI-authored cases await independent review. |
| Prompt-injection suite, 15 Oct 2026 | 0/20 changed fields/policy; model raised a flag in 20/20. | Keyword-only fallback raised 2/20; small synthetic set. |
| Sepolia manifest | `deploymentStatus: deployed`; module and Safe T/O1 addresses, code hashes, verified block 11,924,209. | A deployment artifact, not a public transaction-by-transaction acceptance report. |

The reviewed manifest identifies module `0xD90e961A1d7B68405Fa8b08F03F6917ada9798F5` and Safe T `0xfC6d3DEFe54eC78A2D0759D907B3a6AC37426a75` on chain ID 11155111. These are **contract/wallet addresses, not transaction hashes**. The cited reliability artifact contains no Sepolia run, and the reviewed report does not provide a verified public PAY transaction hash to publish here. A final presentation should add an explorer link only after verifying the exact transaction, request, receipt and postconditions for the claimed scenario. [Sepolia manifest](../deployments/11155111.json) · [reliability](evidence/reliability-2026-10-15.md) · [security evidence](security/test-evidence.md).

### Current limits and next steps

First, run and archive a public Sepolia scenario set with transaction hashes, receipts, postcondition and reconciliation evidence. Second, rerun the planner comparison on reviewed held-out data with algorithm and cost assumptions recorded. Third, independently review contract authorization and signer operations before any mainnet claim. Fourth, test restart, RPC outage, reorg and partial-plan recovery, and confirm live Aave supply headroom and external compliance-provider configuration. AI evaluations need second-person labels and broader document and locale coverage. [Implementation gaps](TECHNICAL_REPORT_EN.md) · [known risks](security/known-risks.md).

**Closing message.** TreasuryPilot's aim is to make stablecoin invoice payment both operable and explainable: a human approves the exact obligation; AI assists with information; a deterministic engine and layered controls limit execution; and every completed transfer can be traced back to the request and verified chain effect. The current repository establishes this architecture and many component behaviors. Public deployment claims should remain tied to dated, reproducible evidence for the specific release.

### Selected sources

- [TreasuryPilot technical report](TECHNICAL_REPORT_EN.md) — full component map and code references.
- [Google project document](https://docs.google.com/document/d/1nkSIU5c-zouBkKooWjEFshxw61pH0CRwugYDy5AFJBo/edit) — product brief and module planning.
- [System architecture](SYSTEM_ARCHITECTURE.md) — service and trust-boundary overview.
- [Sepolia deployment manifest](../deployments/11155111.json) — deployment configuration and verified block.
- [Local reliability report](evidence/reliability-2026-10-15.md) — 30-run Anvil results and zero Sepolia runs.
- [Contract security evidence](security/test-evidence.md) — dated Foundry/fork/Python campaigns.
- [Known risks](security/known-risks.md) — limitations and open risks.
