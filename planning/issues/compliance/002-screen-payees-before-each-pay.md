# [COMPLIANCE] Screen payees before each PAY

| Field | Value |
|---|---|
| **ID** | CMP-002 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-085, M14-D7 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-110: Payee sanctions / blocklist screening

Problem behind this work (from `docs/FEATURES.md`):

- **F-110** solves: Paying sanctioned or known-malicious addresses.

## Objective

A payee that became listed after registration is not paid.

## Scope

- Validator check using the latest screening within TTL
- refresh when stale
- block on HIT or no valid result
- synchronous refresh before PAY with a 5 s timeout when the last result is older than 24 h (M14-D7)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-001: Build the screening adapter and fixture provider
- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations

## Acceptance criteria

- [ ] A payee added to the blocklist after registration blocks the next plan with SCREENING_HIT

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
