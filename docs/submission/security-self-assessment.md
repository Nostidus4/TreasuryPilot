# TreasuryPilot security self-assessment

DOM-011 / #235. Implementation baseline: main
`0c79d0731ad730e7c2f9f6644e90c36453b02d7e`, reviewed for this draft on
2026-10-15. Status: **developer review and operational release review pending**.
Scope: synthetic testnet submission evidence. This is a self-assessment;
independent audit, production certification and legal approval are not established.

## 1. Security boundary and implementation status

TreasuryPilot separates human approval, delegated execution and AI proposals.
Customer funds remain in Safe wallets. The module is the enforcement boundary
for calls made through that module; Safe owner transactions and other enabled
modules remain separate paths. The application must disclose those paths and
cannot promise universal restrictions on owner-controlled funds.

At this baseline, contracts, integer financial-engine primitives, organization
RBAC, invoice intake/approval, maker-checker and HIGH-flag acknowledgment routes,
AI extraction/input controls, read-only tool primitives, chain tracking/indexing,
audit anchoring and deployment/EAS helpers have code. These are implementation
statements, not evidence that the complete payment flow runs autonomously.

The signer service still exposes health only. End-to-end policy authorization,
transaction submission, sequential execution and operational recovery remain
release gates. Policy attestation issue/verification helpers and an optional
on-chain executor wrapper exist; their presence is not an end-to-end authorization
guarantee. Independent authorization review and integrated execution evidence
remain required. Open stacked PRs and this documentation recovery are outside
the pinned implementation baseline.

## 2. Permission tiers

An app role identifies off-chain permissions. Linked wallet signatures and Safe
thresholds establish on-chain authority. Platform administration is not a Safe
owner signature. Multiple roles on one identity do not provide independent
maker-checker assurance.

| Tier     | Authority                                                                                                                                                                                                           | Limits                                                                                                                                                                                                                                                                 | Enforcement and present evidence                                                                                                                                                                                                                                                                                |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Owner    | Safe T governance configures mandate, per-asset policies/buffers, current approvers, payees, exact one-time exceptions, duplicate overrides and borrow/repay grants; can pause, resume, permanently revoke and cancel unpaid requests. | Module governance requires `msg.sender == safeT`, not merely an owner EOA. Exceptions lift only the per-request PAY cap. Existing transactions cannot be reversed by pause/revoke. Owners retain their separate Safe authority.                                        | `TreasuryPilotGovernance.onlyOwner`, explicit governance entry points and `TreasuryPilotModule.authorizeBorrow/authorizeRepay`; actual Safe threshold is enforced by Safe. Governance/access/exception tests and I9/I15 exist. Demo deploy uses one owner and threshold 1, not production multisig assurance.   |
| Approver | A current approver signs an exact request's PaymentApproval; supports EOA and ERC-1271 validation. Can permanently cancel an unpaid request on-chain.                                                               | Cannot raise limits, grant exceptions, register payees, configure executor, resume or move funds merely by holding the approver role. An approval alone does not submit a PAY. One M1 signature is sufficient; n-of-m request approval is Later.                       | Approval domain/13-field hashing, current approver and expiry checks in governance/module; cancellation role check. Maker-checker/solo mode and HIGH-flag acknowledgment are enforced by invoice approval routes; their integration tests are separate from contract evidence.                                                                                               |
| Guardian | Configured guardian or Safe T can pause the module. A Guardian Safe can expose a pause-only sentinel role.                                                                                                          | Guardian cannot resume, revoke, change mandate, grant exceptions or execute money actions solely by virtue of this role. Availability attacks remain possible through repeated pause.                                                                                  | `pause()` accepts only Safe T or mandate guardian; `resume()` is owner-only. Real 1-of-2 Guardian Safe pause/cannot-resume test exists. Public Guardian Safe/sentinel wiring remains deployment work.                                                                                                           |
| Executor | Current mandate executor submits fixed PAY/REFILL/SUPPLY/WITHDRAW, authorized BORROW/REPAY and configured labelled test-router calls.                                                                               | Active/unexpired mandate required. PAY/REFILL require the exact human approval. Floors, budgets, current payee status, cancellation and replay recheck at execution. Borrow/repay require unused owner grants. No generic execute, owner changes or native vendor PAY. | `onlyExecutor`, per-asset policies, fixed lending pool, exact deltas, allowance reset, nonreentrancy and replay mappings. Attestation helpers and an optional executor wrapper exist. Full signer authorization, fresh simulation and release review remain pending; no end-to-end exact-plan execution guarantee is claimed. |
| AI       | Proposes extraction, ordering, explanations and review text under the target read-only tool design. Adapter, untrusted wrapping, instruction detection and secret scanning exist.                                   | AI has no owner/approver/executor authority; confidence is not permission. Draft output cannot register a payee, approve, alter limits, sign or broadcast. Deterministic amounts and human-confirmed terms remain authoritative.                                       | Explicit worker-ai environment/queue separation, fixed system prompt and input controls. Extraction and read-only tool primitives exist; complete planner integration and measured red-team performance are pending; prompt controls alone do not prove absence of downstream side effects.                                                              |

## 3. Control and rule mapping

| Control               | Enforced on chain                                                                                                                                          | Off-chain obligations / limitations                                                                                                                                                   |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Approval authenticity | Domain chain/module binding, exact 13 fields, current approver and expiry, EOA/ERC-1271.                                                                   | Confirmation/approval routes implement creator/editor maker-checker (with explicit solo mode), expiry and HIGH acknowledgments. Route tests are linked below; complete execution remains a release gate.                                                                      |
| PAY authority         | Only operational wallets; active cooled allowlisted payee; approved early/standard amount; request/fingerprint/step/cancellation gates.                    | Invoice truth and metadata preimages are off-chain. The contract does not certify invoice legitimacy.                                                                                 |
| Limits / reserves     | Separate execution-day counters shared across operational wallets; persistent across mandate versions; floors; REFILL bound; static supply floor and caps. | Dynamic PaymentReserve, debt reserve, holds, fee policy and plan ordering are engine/validator responsibilities.                                                                      |
| Exceptions            | Exact request/amount/payee/expiry/current version; atomically consumed; daily/floor/payee constraints remain.                                              | AI can draft an explanation only. Owner governs through Safe T.                                                                                                                       |
| Borrowing             | One-time owner grant, expiry/consumption and instantaneous HF/rate guards; exact allowed pool and cash deltas.                                             | Full plan ID is opaque; future financing costs, snapshot freshness and repayment rationale require owner/engine review.                                                               |
| Recovery              | Replay/cancellation flags protect repeated successful steps.                                                                                               | Unknown outcomes, outbox persistence, sequential execution, nonce reconciliation and reorg handling need worker integration.                                                          |
| Asset operations      | Versioned per-asset PAY/REFILL policies and buffers; primary lending asset/fixed pool; exact balances and allowance reset; labelled fixed test-router ABI.                                                                 | Current Aave availability, asset valuation and production quote freshness are separate checks.                                                                                        |
| Receipt evidence      | EAS registry records the attester's payload.                                                                                                               | Helper checks successful canonical PAY, finalized Sepolia block and trusted attester; four metadata hashes remain backend assertions. Local journal is not distributed deduplication. |

### Known-risk summary

The linked register has 25 proposed risks (KR-01 through KR-25) at its stated historical baseline; its mitigations and dispositions still need review against this baseline. Highest-priority themes, all rated
High impact: unaudited contracts (KR-01), Safe owner and other-module authority
(KR-02), executor-host and policy-key compromise (KR-03, KR-04), LLM extraction
and prompt injection (KR-05, KR-06), RPC trust (KR-07), reorg/Unknown outcomes
(KR-08, KR-09), Aave liquidity limits (KR-11) and fixture screening mistaken for
live coverage (KR-19). Each has a mitigation status and proposed disposition.

See the detailed [C-rule/test mapping](../security/contract-rule-test-mapping.md)
and [known-risk register](../security/known-risks.md).
Risk dispositions in that register are proposed and still require team review.

## 4. Evidence and its limits

This document reads existing source, tests and CI artifacts; no new runtime
security campaign is claimed for this documentation change. Contract files at
the implementation baseline have no diff from CI revision
`02e4d674d1a76aa60cf2ac1c242f2aed20a6fb5c`. That comparison covers `contracts/`,
not every backend dependency, deployment configuration or operational scenario.

| Evidence | Revision / source | What it demonstrates |
| --- | --- | --- |
| 110 passing Foundry tests, zero failures, 16 suites | [Contracts CI at 02e4d67](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38583286706) | Tested paths under Foundry v1.8.5 / solc 0.8.28; aggregate invariant execution is included in the count. Passing tests do not prove all authorization properties or deployment readiness. |
| Invariant and Slither jobs successful | [Security CI at 02e4d67](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38583286728) | Existing invariant suite and static-analysis triage gate pass at that revision. Accepted findings and the [triage](../security/static-analysis.md) qualifications remain relevant. |
| Approval lifecycle, signature and maker-checker tests present | [API approval tests](../../services/api/tests/test_invoice_approval_api.py), [approval builder tests](../../services/api/tests/test_invoice_approval.py) | Source references for backend controls; the contract CI totals above do not measure these tests. |
| Seven pinned Aave cases, repeated local/fork deployment and local PAY-to-EAS | [Historical campaign](../security/test-evidence.md), [PR #291 CI](https://github.com/Nostidus4/TreasuryPilot/pull/291) | Historical fork/local fixture behavior; not current public USDC capacity or public EASScan acceptance. |
| PaymentApproval/PlanAttestation vectors and optional wrapper tests | [Vectors](../../contracts/test/vectors/README.md), [wrapper tests](../../contracts/test/unit/PlanAttestedExecutor.t.sol) | Hash/domain/signature and covered wrapper checks; full authorization review and application integration remain release gates. |

The earlier 86-test campaign at `6b97124` is historical. Its fuzz/invariant and
isolated mutation evidence remains described in the historical campaign;
it must not be represented as current whole-repository coverage.

Unmeasured here: invoice extraction accuracy, planner AI uplift, end-to-end attack
success rate, production recovery reliability and public execution evidence.
Evaluation reports must identify revision, split, denominator, failures, exposure
history and runtime mode. Local test success is not a production audit.

## 5. Deployment and operational acceptance

The committed Sepolia manifest is still configured-only, with no deployed module
or Safe addresses. Issue closure alone does not establish a mined deployment or
a public EASScan sample; record actual explorer links when available. No production/mainnet readiness
or regulatory permission is claimed.

Before the demo operator enables financial execution:

1. Review and merge the chosen source; record exact deployed bytecode/revision.
2. Verify chain, asset/decimals, pool/aToken mapping, Safe owners/thresholds and
   enabled modules; fund the intended owner/executor/attester testnet identities.
3. Verify the broadcaster equals demo owner and the receipt attester is dedicated.
   Publish only from mined state, then verify explorer code and schema.
4. Check live reserve capacity and execution gas; pinned historical success does
   not establish current readiness. Record blocked paths honestly.
5. Demonstrate signer authorization/simulation and Unknown recovery before using
   the target autonomous worker flow; use controlled manual evidence where those
   integrations are absent and label it accordingly.
6. Review pause/cancel/expiry, backup/restore and receipt reconciliation; collect
   public transaction/UID links and a second person's review.

## 6. Reviewer decision

The developer reviewer should confirm permission boundaries, risk claims,
evidence scope and baseline accuracy. Any discrepancy must be corrected before
submission. Approval of this document records a reviewed self-assessment; it does
not waive missing implementation, testnet acceptance or a future external audit.
