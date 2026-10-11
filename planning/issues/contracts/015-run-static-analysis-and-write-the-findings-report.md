# [CONTRACTS] Run static analysis and write the findings report

| Field | Value |
|---|---|
| **ID** | SC-015 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-SEC-07 |
| **Blocks** | DOM-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-163** solves: Evidence for the Security criterion.

## Objective

No unexplained high-severity static-analysis finding remains.

## Scope

- Run Slither
- fix or justify each high/medium finding
- docs/security/static-analysis.md with the triage table

## Out of scope

External audit.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-013: Write the contract acceptance test suite (AT cases)

## Acceptance criteria

- [ ] Report lists every high and medium finding with status Fixed or Accepted (with reason)
- [ ] CI Slither job has no untriaged high findings

## Testing requirements

- Security: Slither in CI

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
