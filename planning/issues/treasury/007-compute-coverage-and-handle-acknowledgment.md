# [TREASURY] Compute coverage and handle acknowledgment

| Field | Value |
|---|---|
| **ID** | TRS-007 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-018, FR-106–107 |
| **Blocks** | EXE-003, WEB-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-012: Module enablement & coverage verification

Problem behind this work (from `docs/FEATURES.md`):

- **F-012** solves: A second module with arbitrary execution would bypass the mandate (GA p.20).

## Objective

Autonomous execution is allowed only when the Safes have exactly the expected module set.

## Scope

- Coverage = COMPLETE if enabled modules equal {TreasuryPilotModule with the expected code hash} and no unexpected guard
- PARTIAL otherwise
- UNKNOWN on read failure
- acknowledge endpoint (Owner)
- coverage exposed to the execution gate

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-005: Read and snapshot Safe configuration
- TRS-006: Build the module deploy-and-enable Safe transaction

## Acceptance criteria

- [ ] An extra module makes coverage PARTIAL and blocks the trigger
- [ ] RPC failure yields UNKNOWN, never COMPLETE
- [ ] Owner acknowledgment is audited and shows a banner state

## Testing requirements

- Integration: AT35-style test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
