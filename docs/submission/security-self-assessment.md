# TreasuryPilot security self-assessment

DOM-011 / #235. Source baseline: main `4b2ee5e89763450078767d564a07f73fabfe2d63`,
2026-10-14. Status: **developer review pending**. Intended use: synthetic testnet
submission evidence. This document is a self-assessment, not an external audit,
production certification or legal approval.

## 1. Security boundary and implementation status

TreasuryPilot separates human approval, delegated execution and AI proposals.
Customer funds remain in Safe wallets. The module is the enforcement boundary
for calls made through that module; Safe owner transactions and other enabled
modules remain separate paths. The application must disclose those paths and
cannot promise universal restrictions on owner-controlled funds.

At this baseline the contracts, financial-engine primitives, organization RBAC,
AI adapter/input controls, RPC primitives, audit primitives and deployment/EAS
helpers have code. The signer service exposes a health endpoint only. Payment
intake/approval integration, worker execution/recovery, production reconciliation
and complete policy-to-signer authorization are not established end-to-end.
Their target behavior in architecture documents must not be reported as deployed
security protection. Open stacked PRs are outside this baseline.

## 2. Permission tiers

An app role identifies off-chain permissions. Linked wallet signatures and Safe
thresholds establish on-chain authority. Platform administration is not a Safe
owner signature. Multiple roles on one identity do not provide independent
maker-checker assurance.

| Tier     | Authority                                                                                                                                                                                                           | Limits                                                                                                                                                                                                                                                                 | Enforcement and present evidence                                                                                                                                                                                                                                                                              |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Owner    | Safe T governance configures mandate, buffers, current approvers, payees, exact one-time exceptions, duplicate overrides and borrow/repay grants; can pause, resume, permanently revoke and cancel unpaid requests. | Module governance requires `msg.sender == safeT`, not merely an owner EOA. Exceptions lift only the per-request PAY cap. Existing transactions cannot be reversed by pause/revoke. Owners retain their separate Safe authority.                                        | `TreasuryPilotGovernance.onlyOwner`, explicit governance entry points and `TreasuryPilotModule.authorizeBorrow/authorizeRepay`; actual Safe threshold is enforced by Safe. Governance/access/exception tests and I9/I15 exist. Demo deploy uses one owner and threshold 1, not production multisig assurance. |
| Approver | A current approver signs an exact request's PaymentApproval; supports EOA and ERC-1271 validation. Can permanently cancel an unpaid request on-chain.                                                               | Cannot raise limits, grant exceptions, register payees, configure executor, resume or move funds merely by holding the approver role. An approval alone does not submit a PAY. One M1 signature is sufficient; n-of-m request approval is Later.                       | Approval domain/13-field hashing, current approver and expiry checks in governance/module; cancellation role check. Maker-checker and HIGH-flag acknowledgment require separate backend integration and evidence.                                                                                             |
| Guardian | Configured guardian or Safe T can pause the module. A Guardian Safe can expose a pause-only sentinel role.                                                                                                          | Guardian cannot resume, revoke, change mandate, grant exceptions or execute money actions solely by virtue of this role. Availability attacks remain possible through repeated pause.                                                                                  | `pause()` accepts only Safe T or mandate guardian; `resume()` is owner-only. Real 1-of-2 Guardian Safe pause/cannot-resume test exists. Public Guardian Safe/sentinel wiring remains deployment work.                                                                                                         |
| Executor | Current mandate executor submits fixed PAY/REFILL/SUPPLY/WITHDRAW, authorized BORROW/REPAY and configured labelled test-router calls.                                                                               | Active/unexpired mandate required. PAY/REFILL require the exact human approval. Floors, budgets, current payee status, cancellation and replay recheck at execution. Borrow/repay require unused owner grants. No generic execute, owner changes or native vendor PAY. | `onlyExecutor`, fixed target/asset/pool, exact deltas, allowance reset, nonreentrancy and replay mappings. Contract negative tests/invariants/forks exist. Signer attestation verification and fresh-simulation service are still unavailable at this baseline.                                               |
| AI       | Proposes extraction, ordering, explanations and review text under the target read-only tool design. Adapter, untrusted wrapping, instruction detection and secret scanning exist.                                   | AI has no owner/approver/executor authority; confidence is not permission. Draft output cannot register a payee, approve, alter limits, sign or broadcast. Deterministic amounts and human-confirmed terms remain authoritative.                                       | Explicit worker-ai environment/queue separation, fixed system prompt and input controls. Complete extraction/planner/tool integration and red-team performance are pending; prompt controls alone do not prove absence of downstream side effects.                                                            |

## 3. Control and rule mapping

| Control               | Enforced on chain                                                                                                                                          | Off-chain obligations / limitations                                                                                                                                                   |
| --------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Approval authenticity | Domain chain/module binding, exact 13 fields, current approver and expiry, EOA/ERC-1271.                                                                   | Human confirmation, creator/editor maker-checker, maximum age and anomaly acknowledgments need backend evidence.                                                                      |
| PAY authority         | Only operational wallets; active cooled allowlisted payee; approved early/standard amount; request/fingerprint/step/cancellation gates.                    | Invoice truth and metadata preimages are off-chain. The contract does not certify invoice legitimacy.                                                                                 |
| Limits / reserves     | Separate execution-day counters shared across operational wallets; persistent across mandate versions; floors; REFILL bound; static supply floor and caps. | Dynamic PaymentReserve, debt reserve, holds, fee policy and plan ordering are engine/validator responsibilities.                                                                      |
| Exceptions            | Exact request/amount/payee/expiry/current version; atomically consumed; daily/floor/payee constraints remain.                                              | AI can draft an explanation only. Owner governs through Safe T.                                                                                                                       |
| Borrowing             | One-time owner grant, expiry/consumption and instantaneous HF/rate guards; exact allowed pool and cash deltas.                                             | Full plan ID is opaque; future financing costs, snapshot freshness and repayment rationale require owner/engine review.                                                               |
| Recovery              | Replay/cancellation flags protect repeated successful steps.                                                                                               | Unknown outcomes, outbox persistence, sequential execution, nonce reconciliation and reorg handling need worker integration.                                                          |
| Asset operations      | Fixed stablecoin/pool; exact balances and allowance reset; labelled fixed test-router ABI.                                                                 | Current Aave availability, asset valuation and production quote freshness are separate checks.                                                                                        |
| Receipt evidence      | EAS registry records the attester's payload.                                                                                                               | Helper checks successful canonical PAY, finalized Sepolia block and trusted attester; four metadata hashes remain backend assertions. Local journal is not distributed deduplication. |

See the detailed [C-rule/test mapping](../security/contract-rule-test-mapping.md)
and [known-risk register](../security/known-risks.md) (KR-01 through KR-25).
Risk dispositions in that register are proposed and still require team review.

## 4. Evidence and its limits

Evidence was read from existing artifacts; no new runtime test campaign is claimed
for this documentation change. Contract/helper sources have no diff between
verified CI revision `6b97124b5e739a439d5aa531aabe40a0233daf24` and the source baseline
above. Other modules changed independently, so historic Python totals are not
represented as current whole-repository coverage.

| Evidence                                                                              | Revision / source                                                                                                    | What it demonstrates                                                                                                                                                                          |
| ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 86 passing Foundry tests, zero failures; 10,000-case fuzz                             | [Contracts CI at 6b97124](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38360625984)                       | Tested module/Safe/asset paths under pinned Foundry v1.8.5 and solc 0.8.28. Foundry reports the 16 invariant properties as one aggregate suite result.                                        |
| I1-I16, 10,000 runs / depth 32 / 320,000 calls, zero unexpected reverts               | [Security CI at 6b97124](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38360626051)                        | Handler assertions across authority, budgets, floors, exceptions, cancellation, replay, lending and exact options. Finite randomized evidence, not a mathematical proof.                      |
| Isolated step-guard / borrow-used-guard mutations detected by I5/I15; source restored | Same security CI                                                                                                     | Demonstrates sensitivity to those two isolated defects, not every possible mutation.                                                                                                          |
| Slither exact-fingerprint gate passes                                                 | Same security CI; [triage](../security/static-analysis.md)                                                           | No untriaged High/Medium. The report includes accepted findings; this is not a finding-free or externally audited codebase.                                                                   |
| Seven pinned Aave cases, repeated local/fork deployment and local PAY-to-EAS          | [Recorded campaign](../security/test-evidence.md), [PR #291 CI](https://github.com/Nostidus4/TreasuryPilot/pull/291) | Historical pool/USDC/LINK and local fixture behavior, finality refusals, publisher checks and retry recovery. Does not establish live USDC capacity or public EASScan acceptance.             |
| Independent PaymentApproval/PlanAttestation vectors and function gas artifact         | Contract/security workflows                                                                                          | Cross-implementation hashes/domain/signature checks and test-profile gas. PlanAttestation encoder is test-only; no module policy authority is added. Gas is not a live network fee guarantee. |

Unmeasured at this baseline: invoice extraction accuracy, planner AI uplift,
end-to-end attack success rate, production recovery reliability and public testnet
acceptance. Synthetic datasets and future evaluation results must identify their
revision, split, denominator, failures, exposure history and actual runtime mode.

## 5. Deployment and operational acceptance

Public Sepolia deployment and an EASScan sample remain #70/#31/#84 work. The
committed public manifest is configured-only. No production/mainnet readiness
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
