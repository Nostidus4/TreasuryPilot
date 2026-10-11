# TreasuryPilot: Functional Requirements

**Status:** Draft for gate G1 · **Date:** 2026-10-10

Each requirement is testable and traces back to a feature (`F-xxx`, see `FEATURES.md`) and, where relevant, to a business rule (`BR-xxx`). The Phase/Priority of a requirement follows its feature unless it says otherwise.

Wording: **shall** = mandatory · **should** = recommended.

## FR-0xx · Identity & Access

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-001 | The system shall allow a user to sign up and sign in with an email address, verified by a one-time link or a password. | F-001 | |
| FR-002 | The system shall rate-limit authentication attempts per IP address and per account. | F-001 | |
| FR-003 | The system shall expire sessions after a configurable idle time and an absolute lifetime. | F-001 | |
| FR-004 | The system shall let a user link an EVM address by verifying a SIWE (EIP-4361) signature that contains a single-use nonce, the domain and the chainId. | F-002 | BR-006 |
| FR-005 | The system shall verify ERC-1271 signatures for contract-wallet addresses. | F-002 | |
| FR-006 | The system shall reject linking an address that is already linked to another user. | F-002 | |
| FR-007 | The system shall allow an authenticated user to create an organization and shall assign that user the OrgAdmin role. | F-003 | |
| FR-008 | The system shall isolate all data by organization and shall reject cross-organization access on every endpoint. | F-003 | BR-093 |
| FR-009 | The system shall present an onboarding checklist (members → treasury → mandate → payees → first invoice) and persist its progress. | F-003 | |
| FR-010 | The system shall allow an OrgAdmin to invite members by email with an expiring invitation and one or more roles. | F-004 | |
| FR-011 | The system shall support the roles Owner, Approver, Operator, Finance, Guardian, OrgAdmin, Auditor and PlatformAdmin, and enforce role-based permissions on every API call. | F-004 | |
| FR-012 | The system shall keep signer roles inactive until the member has linked a wallet. | F-004 | BR-006 |
| FR-013 | The system shall prevent removing the last OrgAdmin or the last Owner of an organization. | F-004 | |
| FR-014 | The system shall reject an approval by the request's creator or last editor. | F-005 | BR-005 |
| FR-015 | The system shall support an Owner-enabled "solo mode" that is recorded on every affected record and in the audit log. | F-005 | BR-005 |
| FR-016 | *(Later)* The system shall require a second factor (TOTP/WebAuthn) for signer roles, and step-up re-authentication for sensitive actions. | F-006 | |
| FR-017 | *(Later)* The system shall support OIDC/SAML SSO with group-to-role mapping and deprovisioning within 5 minutes. | F-007 | |

## FR-1xx · Treasury & Wallets

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-101 | The system shall allow an Owner or OrgAdmin to create a treasury with one supported chain, one payment stablecoin, one source wallet `T` and one or more operational wallets. | F-010 | |
| FR-102 | The system shall reject a treasury with duplicate wallets, wallets on another chain, or non-Safe wallets in protected mode. | F-010 | BR-018 |
| FR-103 | The system shall read each Safe's owners, threshold, enabled modules and guard, and store a snapshot that references a block. | F-011 | |
| FR-104 | The system should support deploying a new Safe from the UI through an Owner-signed transaction. | F-011 | |
| FR-105 | The system shall detect changes to a Safe's configuration within one polling interval and raise a coverage event. | F-011, F-012 | |
| FR-106 | The system shall compute coverage (COMPLETE / PARTIAL / UNKNOWN) by comparing enabled modules to an allowlist of known module code hashes. | F-012 | BR-018 |
| FR-107 | The system shall suspend autonomous execution for a treasury whose coverage is not COMPLETE, unless the Owner has acknowledged it explicitly. | F-012 | BR-018 |
| FR-108 | The system shall identify assets by `(chainId, address)`, verify decimals on-chain, and label test assets. | F-013 | BR-083 |
| FR-109 | The system shall represent all monetary amounts as non-negative integers in base units in storage, APIs and contracts. | F-013 | BR-083 |
| FR-110 | *(Later)* The system shall support multiple treasuries per organization on different chains, with isolated counters. | F-014 | |
| FR-111 | *(Later)* The system shall support multiple stablecoins per treasury, with limits per asset. | F-015 | |

## FR-2xx · Mandate & Policy

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-201 | The system shall allow only the Owner to create a mandate draft with: actions, wallets, refill paths, payees, per-request and daily limits per action and asset, buffer and target per wallet and asset, swap settings, gas funding cap, and validity window. | F-020 | BR-002 |
| FR-202 | The system shall reject an incomplete or inconsistent mandate draft (e.g., `target < buffer`, a missing gas cap, a missing router while SWAP is enabled). | F-020 | BR-014 |
| FR-203 | The system shall render a human-readable summary of a mandate and its diff against the active version before signing. | F-020, F-134 | |
| FR-204 | The system shall build an Owner-signable Safe transaction to activate or update a mandate, and mark it Active only after the confirmed on-chain state matches the draft. | F-021 | BR-015 |
| FR-205 | The system shall keep an immutable version history of mandates. | F-021 | |
| FR-206 | The contract shall invalidate outstanding exceptions on a version change and shall not reset counters. | F-021 | BR-016 |
| FR-207 | The contract shall reject execution after the mandate's expiry. | F-021 | |
| FR-208 | The system shall allow an Owner to register a payee on the on-chain allowlist with `activeFrom = now + coolingPeriod`. | F-022 | BR-013, BR-017 |
| FR-209 | The contract shall reject PAY to a payee that is unregistered, deactivated, or still cooling. | F-022 | BR-013 |
| FR-210 | The system shall treat a payee address change as a new entry that restarts cooling, and shall deactivate the old entry. | F-022 | BR-017 |
| FR-211 | The system shall allow an Operator to propose a payee, which the Owner reviews and signs. | F-022 | |
| FR-212 | The contract shall enforce per-request and daily limits per `(treasury, action, asset, UTC day)`. | F-023 | BR-020–022 |
| FR-213 | The contract shall increment counters only on successful execution, in the same transaction. | F-023 | BR-025 |
| FR-214 | The contract shall evaluate a pending step against the budget of the day it executes. | F-023 | BR-026 |
| FR-215 | The contract shall reject any PAY or REFILL that would leave the affected wallet below its minimum buffer. | F-024 | BR-030 |
| FR-216 | The system shall let the Owner grant a one-time exception through a Safe T governance transaction (`grantException`) bound to the fields in BR-041. | F-025 | BR-041, BR-043 |
| FR-217 | The contract shall accept an exception only to lift the per-request cap, consume it atomically with the PAY, and count the full amount toward the daily cap. | F-025 | BR-040, BR-042 |
| FR-218 | The system shall allow the Owner or Guardian to request a pause. The backend shall stop planning and submitting immediately. | F-026 | BR-063 |
| FR-219 | The contract shall reject execution while the mandate is paused or revoked. | F-026 | BR-062 |
| FR-220 | The contract shall allow only the Owner to resume or revoke. | F-026 | BR-064 |
| FR-221 | The UI shall distinguish "pause requested" from "pause effective on-chain", and list pending transactions. | F-026 | |
| FR-222 | The system shall auto-pause the backend and notify the Owner when circuit-breaker thresholds are crossed. | F-027 | BR-065 |
| FR-223 | *(Later)* The contract shall store and enforce reservations and execution holds for registered obligations. | F-028 | BR-035 |
| FR-224 | *(Later)* The contract shall enforce k-of-n approval thresholds by amount band. | F-029 | |
| FR-225 | The system shall build Safe transactions for every governance change (bundled with MultiSend), collect and verify owner signatures in the app, give the last owner the execution call, and track the result. | F-020–F-026 | BR-008 |

## FR-3xx · Invoices & Requests

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-301 | The system shall allow an Operator to create a payment request manually with: invoice reference, payee, asset, amount, paying wallet, due date, optional terms and attachments. | F-030 | |
| FR-302 | The system shall reject requests whose asset is not the treasury's payment stablecoin (M1). | F-030 | BR-073 |
| FR-303 | The system shall accept PDF, PNG and JPG uploads up to 10 MB, store them privately, and create a draft with AI-extracted fields that carry source references. | F-031 | BR-074, BR-075 |
| FR-304 | The system shall fall back to manual entry, showing the document, when extraction fails or times out. | F-031 | |
| FR-305 | The system shall never change a registered payee address based on extracted invoice content. | F-031 | BR-072 |
| FR-306 | The system shall import a CSV per the published template, validate rows independently, create drafts for valid rows, and produce a per-row error report. | F-032 | |
| FR-307 | The system shall neutralize spreadsheet-formula injection in CSV input and output. | F-032, F-073 | |
| FR-308 | *(Later)* The system shall provide a per-organization inbound email address that turns invoice emails into drafts, with sender verification. | F-033 | |
| FR-309 | *(Later)* The system shall expose an idempotent, scoped API for creating draft requests. | F-034 | |
| FR-310 | The system shall extract payment terms (discount %, discount deadline, net due date, late-fee schedule, priority note) into a structured form for human confirmation. | F-035 | BR-075 |
| FR-311 | The system shall use only human-confirmed terms in scheduling. | F-035 | BR-075 |
| FR-312 | The system shall flag: payee address differing from the registry or history, amount outliers versus vendor history, duplicate fingerprints, instruction-like text, currency or chain mismatch, and due-date anomalies. Each flag shall carry a severity, evidence and a reason code. | F-036 | BR-072 |
| FR-313 | The system shall require explicit Approver acknowledgment of high-severity flags before signing. | F-036, F-131 | |
| FR-314 | The system shall compute a normalized invoice fingerprint and warn on duplicates at intake. | F-037 | BR-071 |
| FR-315 | The contract shall reject a PAY whose fingerprint has already been paid, unless the Owner has called `allowDuplicate(fingerprint, requestId)` for that request. | F-037 | BR-071 |
| FR-316 | The system shall let an Approver sign EIP-712 typed data binding the BR-003 fields, and shall record the approval only after verifying the signature. | F-038 | BR-003, BR-004 |
| FR-317 | The system shall invalidate an approval when any bound field changes. | F-038 | BR-003 |
| FR-318 | The contract shall verify the approval signature against the current approver set at PAY time. | F-038 | BR-004 |
| FR-319 | The system shall enforce the request state machine (`Draft → AwaitingApproval → Approved → Scheduled → Planning → Preparing → Paying → Paid`; branches `Rejected`, `AwaitingAuthority`, `NeedsReview`, `Expired`, `Cancelled`) and reject illegal transitions. | F-039 | |
| FR-320 | The system shall prevent cancelling a request while a PAY transaction is pending or unknown. | F-039 | BR-060 |
| FR-321 | *(Later)* The system shall generate recurring drafts that each require approval. | F-040 | BR-002 |
| FR-322 | *(Later)* The system shall support fiat-denominated invoices with an approved maximum stablecoin amount, FX tolerance and depeg check. | F-041 | |
| FR-323 | The system shall flag near-duplicate requests per BR-076 and require acknowledgment of the HIGH variant. | F-036, F-037 | BR-076 |
| FR-324 | The system shall offer and track an on-chain cancellation for any cancelled request that was ever approved, and the contract shall reject refill and pay for a cancelled request id. | F-039 | BR-077 |

## FR-4xx · Planning

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-401 | The system shall read balances, mandate state, counters, payee status and module configuration at a single block, and record the block number, hash, time and coverage. | F-050 | BR-051 |
| FR-402 | The system shall refuse to plan or execute on a snapshot that is stale beyond the configured threshold, or that has coverage other than COMPLETE. | F-050 | |
| FR-403 | The system shall compute Available, FundingDeficit, Shortage, PreferredRefill, refill Bound, SourceCapacity and Cap per the domain formulas using integer arithmetic. | F-051 | BR-032, BR-034, BR-036 |
| FR-404 | The system shall stop and report when `Cap < Shortage`. | F-051 | BR-033 |
| FR-405 | The system shall compute a schedule over a rolling horizon (≤ 30 UTC days) that optimizes the BR-052 objective with a CP-SAT solver (EDF fallback), deterministically, and report binding constraints and infeasible items with reasons. | F-052 | BR-052, ADR-015 |
| FR-406 | The system shall obtain an AI plan proposal as structured output (order, deferrals, exception requests, rationale, evidence ids) using read-only tools only. | F-053 | BR-002 |
| FR-407 | The system shall score the AI proposal with the deterministic objective and choose the better feasible plan, logging the comparison. | F-053 | BR-052 |
| FR-408 | The system shall discard invalid or out-of-mandate AI plans and route them to NeedsReview. | F-053 | BR-056 |
| FR-409 | The system shall use a tested rule-based template when the AI is unavailable, only under the BR-055 conditions, and record `RULE_BASED`. | F-054 | BR-055 |
| FR-410 | The system shall validate every execution plan (stage PLAN) and every step on a fresh snapshot (stage PRE_STEP) and by simulation (stage SIMULATION), returning ALLOW / NEEDS_APPROVAL / BLOCK with all failing reason codes, a primary code, and warnings. | F-055 | BR-010, BR-051, BR-067 |
| FR-411 | The system shall never return ALLOW when required data is missing or any operation is Unknown. | F-055 | BR-060 |
| FR-412 | The system shall attest each ALLOWed execution plan (one request) by signing EIP-712 `PlanAttestation` data that binds planHash, request and step ids, policy version, executor, validUntil, nonce and evidence digest. | F-056 | BR-059 |
| FR-413 | The system shall reject execution of a step that differs from its attested plan, or whose attestation has expired. | F-056 | BR-059 |
| FR-414 | The system shall draft an exception request for the Owner on NEEDS_APPROVAL, with the numbers taken from the engine. | F-057 | BR-043 |
| FR-415 | The system should project 7-day runway per wallet from approved obligations, and suggest pre-emptive refills within the limits. | F-058 | |
| FR-416 | *(Later)* The system shall support mandated refills between operational wallets without underfunding the source wallet's obligations. | F-059 | BR-012 |

## FR-5xx · Execution

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-501 | The system shall trigger planning automatically when approved requests enter their execution window or on relevant events, without user action. | F-060 | |
| FR-502 | The system shall hold a single-flight lock per treasury so that only one request's steps execute at a time. | F-060, F-061 | BR-050 |
| FR-503 | The system shall skip triggers while the treasury is paused, has coverage other than COMPLETE, or has an Unknown operation. | F-060 | BR-060, BR-063 |
| FR-504 | The system shall provide an Operator "run now" action subject to the same checks. | F-060 | |
| FR-505 | The executor shall simulate the exact call before signing, and shall not broadcast if the simulation reverts. | F-061 | |
| FR-506 | The executor shall persist the operation (nonce, txHash) before broadcast (outbox), and track replacements as the same operation. | F-061 | BR-061 |
| FR-507 | The signer service shall sign only payloads that carry a valid attestation from the validator. | F-061 | BR-092 |
| FR-508 | The contract shall execute REFILL only to the approval's paying wallet, once per request per wallet, within refill limits and the source buffer, with the post-refill balance ≤ approval amount + target, and mark the step id used. | F-062 | BR-012, BR-030, BR-036 |
| FR-509 | The contract shall execute PAY only after verifying approval, payee status, fingerprint, request unused, limits or exception, buffer, and that the mandate is not paused. It shall then mark the request used and update counters atomically. | F-063 | BR-001, BR-010 |
| FR-517 | The system shall propose a per-plan fee threshold, a daily fee budget and a speed preset from recent fee history, for the Owner to accept. | F-066 | BR-084 |
| FR-518 | The system shall hold plans above the fee threshold or budget, defer them while the deadline allows, and request fee acceptance from Finance, Operator or Owner on the last safe day. | F-066 | BR-084 |
| FR-510 | The contract shall emit events for every REFILL, PAY, SWAP, exception consumption, pause, resume and mandate change, including request and step ids. | F-062, F-063, F-120 | |
| FR-511 | The contract shall execute SWAP only via an allowlisted adapter, router and pair, within the swap budget, with engine-computed minOut, exact allowance, and allowance reset to 0. | F-064 | BR-081, BR-082 |
| FR-512 | The system shall label the M1 test router as a test router everywhere. | F-064 | BR-095 |
| FR-513 | *(Later)* The contract shall verify signed quotes from allowlisted sources for production swaps. | F-065 | |
| FR-514 | The system shall record the actual fee for every transaction, including reverts, and alert when executor gas falls below its threshold. | F-066 | BR-025, BR-080 |
| FR-515 | The system shall stop with a clear reason when no gas source is available. | F-066 | |
| FR-516 | *(Later)* The system shall bridge via allowlisted bridges without counting in-flight funds and without re-sending on timeout. | F-067 | |

## FR-6xx · Verification & Reconciliation

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-601 | The system shall track transactions through `NotSubmitted / Submitted / Pending / Confirmed / Reverted / Unknown` with the confirmation depth configured per chain. | F-070 | BR-053 |
| FR-602 | The system shall detect reorgs by block hash and re-evaluate the affected states. | F-070 | |
| FR-603 | The system shall verify each confirmed step's post-conditions (balance deltas, used flags, allowance 0, counters), and record PASSED / DISCREPANCY / UNKNOWN. | F-071 | |
| FR-604 | The system shall route discrepancies to NeedsReview and the circuit breaker. | F-071 | BR-065 |
| FR-605 | The system shall link every request to all of its transactions and fees, and classify each as internal transfer, conversion or external expense. | F-072 | BR-096 |
| FR-606 | The system shall maintain reconciliation states `NotReady / Pending / Matched / Discrepancy`, and allow Finance to mark Matched. | F-072 | BR-096 |
| FR-607 | The system shall export reconciliation CSV and journal lines for a period, with totals equal to on-chain totals. | F-073 | |
| FR-608 | The system should publish an on-chain attestation for each paid or matched request containing no personal data. | F-074 | BR-074 |
| FR-609 | *(Later)* The system shall sync bills and payments with ERP systems without ever approving a payment from a sync. | F-075 | BR-001 |

## FR-7xx · Recovery

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-701 | On restart or Unknown status, the system shall resolve every in-flight operation from the outbox, the chain and contract used-flags before any new action. | F-080 | BR-060 |
| FR-702 | The system shall block execution for a treasury while any operation is Unknown. | F-080 | BR-060 |
| FR-703 | The system shall record partial completion and resume from the first unfinished step after re-validation, never redoing completed steps. | F-081 | BR-054 |
| FR-704 | The system shall create exactly one NeedsReview item per non-ALLOW outcome, with a classification, reason codes, completed steps and role-specific actions. | F-082 | |
| FR-705 | The system shall route over-cap items to the Owner, payee/budget issues to the Owner's policy edit, and amount/payee changes to re-approval. | F-082 | BR-002 |
| FR-706 | The system shall retry retryable errors with exponential backoff and a maximum number of attempts, reusing all identifiers. | F-083 | BR-061 |

## FR-8xx · AI

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-801 | The system shall provide a Copilot that answers treasury questions using only read-only and simulation tools, citing tool outputs for every number. | F-090 | BR-034 |
| FR-802 | The Copilot shall refuse execution requests and point the user to the approval flow. | F-090 | BR-002 |
| FR-803 | The system shall wrap all external content as labelled, untrusted data, limit its length, use strict output schemas and tool allowlists, and validate outputs before use. | F-091 | BR-070 |
| FR-804 | The system shall never include secrets, keys or reusable signatures in LLM inputs. | F-091 | BR-092 |
| FR-805 | The system shall provide a one-command benchmark comparing B1 and B2 on 30+ scenarios, reporting savings, on-time %, exceptions, tx count, fees, violations, latency and cost. | F-092 | |
| FR-806 | The system shall log each AI call: purpose, model and version, prompt version, input references, tool calls, output, validation result, plannerSource, latency and cost. | F-093 | |
| FR-807 | The system shall fail planning closed if the AI decision log cannot be written. | F-093 | BR-097 |
| FR-808 | The system shall route LLM calls through a provider-agnostic adapter with per-task model selection, timeouts and provider fallback. | F-094 | |

## FR-9xx · Notifications, Compliance, Audit, UX, Analytics, Admin, DevEx

| ID | Requirement | Feature | BR |
|---|---|---|---|
| FR-901 | The system shall deliver in-app notifications for: approval needed, exception needed, payment done, needs review, pause, anomaly and low gas, routed by role and deduplicated by event id. | F-100 | |
| FR-902 | The system should deliver the same events to a linked Telegram chat with deep links, and shall not allow actions from Telegram. | F-101 | |
| FR-903 | *(Later)* The system shall deliver email notifications and digests. Security events cannot be unsubscribed. | F-102, F-105 | |
| FR-904 | *(Later)* The system shall send HMAC-signed webhooks with retries and a dead-letter queue. | F-103 | |
| FR-905 | *(Later)* The system shall support Slack, Lark and WeCom channels. | F-104 | |
| FR-906 | The system shall screen payee addresses at registration and before PAY through a provider adapter, and BLOCK on a hit. | F-110 | BR-085 |
| FR-907 | *(Later)* The system shall gate mainnet treasury activation on KYB approval. | F-111 | |
| FR-908 | *(Later)* The system shall support Travel Rule data exchange for qualifying transfers. | F-112 | |
| FR-909 | The system shall store only hashes and commitments on-chain, encrypt confidential data at rest, and redact logs. | F-113 | BR-074 |
| FR-910 | *(Later)* The system shall support configurable retention, deletion workflows and region pinning. | F-114 | |
| FR-911 | The system shall write an append-only, hash-chained audit record for every user action, state transition, validation decision, AI decision and transaction. | F-120 | BR-097 |
| FR-912 | The system shall provide a script that verifies the integrity of the audit chain. | F-120 | |
| FR-913 | The system shall export a per-request evidence bundle that validates against a published JSON schema and contains no fabricated hashes. | F-121 | BR-095 |
| FR-914 | The system shall attach coverage labels to assessments, snapshots and statuses, and use precise status wording. | F-122 | |
| FR-915 | The UI shall provide a treasury dashboard showing balances against buffer and target, budget used, coverage, mandate state, queues, runway and activity. | F-130 | |
| FR-916 | The UI shall provide an approval inbox with the document, the extracted fields, a history diff, flags with evidence, and wallet signing. | F-131 | |
| FR-917 | The UI shall show plan cards and a live per-step timeline with explorer links, separating validator reasons from AI explanations. | F-132 | BR-057 |
| FR-918 | The UI shall provide a reconciliation view with filters, mark-matched, discrepancy notes and export. | F-133 | |
| FR-919 | The UI shall provide mandate and payee management with diffs, cooling countdowns, screening results and Owner signing. | F-134 | |
| FR-920 | The UI shall provide an exception and review console with role-specific actions per item type. | F-135 | |
| FR-921 | The system shall compute operational metrics from raw events, including blocked or rejected requests. | F-140 | |
| FR-922 | The system shall report savings against the B1 counterfactual with its methodology. | F-141 | |
| FR-923 | The system shall emit structured logs, metrics and traces correlated by request, plan and operation ids, and shall raise alerts. | F-142 | |
| FR-924 | *(Later)* The system shall provide a PlatformAdmin console without any fund-moving capability. | F-150 | BR-094 |
| FR-925 | The system shall load and validate chain, RPC, contract and asset configuration at startup, and fail fast if it is invalid. | F-151 | |
| FR-926 | *(Later)* The system shall meter usage and bill organizations without deducting fees from their treasuries. | F-152 | BR-091 |
| FR-927 | The repository shall start the full stack with seeded scenarios through a single documented command. | F-160 | |
| FR-928 | CI shall run lint, typecheck, unit, contract (including fuzz and invariant), static analysis, integration and build on every PR. | F-161 | |
| FR-929 | The scenario runner shall execute named scenarios only on allowlisted test chains and emit evidence bundles. | F-162 | BR-095 |
| FR-930 | The security suites shall cover at least 8 contract invariants, contract-bypass attempts, and 20 prompt-injection invoices. | F-163 | |
| FR-931 | The reliability harness shall run the main scenario 30× on a local chain and 10× or more on testnet, and report the results. | F-164 | |
