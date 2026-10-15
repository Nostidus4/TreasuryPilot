# TreasuryPilot security self-assessment

DOM-011 / #235. Implementation baseline and CI revision: see the
[submission README](README.md#baseline-and-evidence-revisions). Status: **developer review and operational release review pending**.
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

| Tier     | Authority                                                                | Key limit                                                    | Enforcement                                                           |
| -------- | ------------------------------------------------------------------------ | ------------------------------------------------------------ | --------------------------------------------------------------------- |
| Owner    | Safe T governance: mandate, policies, approvers, payees, exceptions, grants; pause, resume, revoke, cancel | Governance requires `msg.sender == safeT`                    | `TreasuryPilotGovernance.onlyOwner`; Safe threshold enforced by Safe  |
| Approver | Signs an exact request's PaymentApproval (EOA or ERC-1271); can cancel an unpaid request | Cannot raise limits, grant exceptions or move funds          | 13-field approval hashing, approver and expiry checks                 |
| Guardian | Pauses the module; a Guardian Safe can expose a pause-only sentinel role | Cannot resume, revoke, change mandate or execute             | `pause()` limited to Safe T or guardian; `resume()` owner-only        |
| Executor | Submits fixed PAY/REFILL/SUPPLY/WITHDRAW, authorized BORROW/REPAY, labelled test-router calls | Active mandate; exact approval for PAY/REFILL; no generic execute | `onlyExecutor`, per-asset policies, fixed pool, replay mappings       |
| AI       | Proposes extraction, ordering, explanations and review text              | No owner, approver or executor authority; confidence is not permission | Worker-ai separation, fixed system prompt, input controls             |

Qualifications:

- **Owner.** Exceptions lift only the per-request PAY cap. Pause/revoke cannot
  reverse existing transactions, and owners keep their separate Safe authority.
  Demo deploy uses one owner and threshold 1, not production multisig assurance.
  Governance/access/exception tests and I9/I15 exist.
- **Approver.** An approval alone does not submit a PAY. One M1 signature is
  sufficient; n-of-m request approval is Later. Maker-checker/solo mode and HIGH-flag
  acknowledgment are enforced by invoice approval routes, whose integration tests
  are separate from contract evidence.
- **Guardian.** Repeated pause remains an availability attack. A real 1-of-2
  Guardian Safe pause/cannot-resume test exists; public Guardian Safe/sentinel
  wiring remains deployment work.
- **Executor.** Floors, budgets, current payee status, cancellation and replay are
  rechecked at execution; borrow/repay need unused owner grants; no owner changes
  or native vendor PAY. Attestation helpers and an optional executor wrapper exist,
  but full signer authorization, fresh simulation and release review remain
  pending. No end-to-end exact-plan execution guarantee is claimed.
- **AI.** Draft output cannot register a payee, approve, alter limits, sign or
  broadcast; deterministic amounts and human-confirmed terms stay authoritative.
  Extraction and read-only tool primitives exist (adapter, untrusted wrapping,
  instruction detection, secret scanning). Complete planner integration and
  measured red-team performance are pending, and prompt controls alone do not prove
  absence of downstream side effects.

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

The [known-risk register](../security/known-risks.md) lists the proposed risks with
their ratings, mitigation status and dispositions. It carries its own historical
baseline, and its content still needs review against this baseline. Its
highest-priority themes include unaudited contracts, Safe owner and other-module
authority, executor-host and policy-key compromise, LLM extraction and prompt
injection, RPC trust, reorg/Unknown outcomes, Aave liquidity limits and fixture
screening mistaken for live coverage.

See the detailed [C-rule/test mapping](../security/contract-rule-test-mapping.md).
Risk dispositions in that register are proposed and still require team review.

## 4. Evidence and its limits

This document reads existing source, tests and CI artifacts; no new runtime
security campaign is claimed for this documentation change. Contract files at
the implementation baseline have no diff from the CI revision (see the
[README](README.md#baseline-and-evidence-revisions)). That comparison covers
`contracts/`, not every backend dependency, deployment configuration or
operational scenario. Reproduction commands follow the table.

| Evidence | Revision / source | What it demonstrates |
| --- | --- | --- |
| 110 passing Foundry tests, zero failures, 16 suites | [Contracts CI run 38583286706, 2026-10-14](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38583286706) | Tested paths under Foundry v1.8.5 / solc 0.8.28; aggregate invariant execution is included in the count. Passing tests do not prove all authorization properties or deployment readiness. |
| Invariant and Slither jobs successful | [Security CI run 38583286728, 2026-10-14](https://github.com/Nostidus4/TreasuryPilot/actions/runs/38583286728) | Existing invariant suite and static-analysis triage gate pass at that revision. Accepted findings and the [triage](../security/static-analysis.md) qualifications remain relevant. |
| Approval lifecycle, signature and maker-checker tests present | [API approval tests](../../services/api/tests/test_invoice_approval_api.py), [approval builder tests](../../services/api/tests/test_invoice_approval.py) | Source references for backend controls; the contract CI totals above do not measure these tests. |
| Seven pinned Aave cases, repeated local/fork deployment and local PAY-to-EAS | [Historical campaign](../security/test-evidence.md), [PR #291 CI](https://github.com/Nostidus4/TreasuryPilot/pull/291) | Historical fork/local fixture behavior; not current public USDC capacity or public EASScan acceptance. |
| PaymentApproval/PlanAttestation vectors and optional wrapper tests | [Vectors](../../contracts/test/vectors/README.md), [wrapper tests](../../contracts/test/unit/PlanAttestedExecutor.t.sol) | Hash/domain/signature and covered wrapper checks; full authorization review and application integration remain release gates. |

Reproduction (runs dated 2026-10-14; `<CI revision>` and `<baseline SHA>` are in the README):

```sh
# no contract diff between CI revision and baseline (empty output expected)
git diff --stat <CI revision> <baseline SHA> -- contracts/
# test/suite counts: run at the baseline (contracts are identical); Foundry v1.8.5 via docker
make test-contracts
# or read the CI logs
gh run view 38583286706 --repo Nostidus4/TreasuryPilot --log
gh run view 38583286728 --repo Nostidus4/TreasuryPilot --log
```

Fuzz/invariant run counts differ by profile and branch (`contracts/foundry.toml`,
`.github/workflows/contracts.yml`), so compare pass/fail and test/suite counts,
not run times. The local command was not re-run for this documentation change.

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
