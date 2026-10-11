# [AGENT] Build the red-team suite runner

| Field | Value |
|---|---|
| **ID** | AGT-015 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-SEC-06, FR-930 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-091: Untrusted-data boundary & prompt-injection defense
- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-091** solves: Injected instructions changing payees or limits.
- **F-163** solves: Evidence for the Security criterion.

## Objective

Prove injected invoices cannot change fields or policy.

## Scope

- Runner over evals/redteam through the real intake pipeline
- assertions: payee, amount, limits and mandate unchanged, flag raised
- results table

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-006: Detect instruction-like text in documents
- DOM-006: Author the red-team invoice set (20)

## Acceptance criteria

- [ ] 0 of 20 cases change any field or policy
- [ ] Each case reports whether a flag was raised

## Testing requirements

- Security: AI red-team

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
