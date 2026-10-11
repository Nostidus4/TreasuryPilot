# [CONTRACTS] Write direct-call bypass tests

| Field | Value |
|---|---|
| **ID** | SC-020 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | NFR-SEC-01 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-163** solves: Evidence for the Security criterion.

## Objective

Show that skipping the backend does not skip the rules.

## Scope

- Tests calling the module directly as executor with: altered payee, altered amount, unapproved request, cooling payee, over daily limit, paused state
- tests calling as a random address

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

These become demo evidence (reverted transactions).

## Dependencies

- SC-013: Write the contract acceptance test suite (AT cases)

## Acceptance criteria

- [ ] Every C-rule in BUSINESS_RULES.md that M1 implements has a direct-call test
- [ ] All revert with the documented error

## Testing requirements

- Security: bypass suite

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
