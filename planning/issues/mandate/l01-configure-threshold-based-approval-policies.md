# [MANDATE] Configure threshold-based approval policies

| Field | Value |
|---|---|
| **ID** | MDT-L01 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-224 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-029: Threshold-based multi-level approval (n-of-m)

Problem behind this work (from `docs/FEATURES.md`):

- **F-029** solves: Enterprise internal controls.

## Objective

Let owners define k-of-n approvals by amount band.

## Scope

- Policy model and UI/API
- collection of multiple approver signatures

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-002: Validate mandate drafts and generate summary and diff
- SC-L02: Enforce n-of-m approval thresholds by amount band

## Acceptance criteria

- [ ] A request in a band needing two approvals is not Approved after one

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
