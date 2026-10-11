# [EXECUTION] Sequence steps with re-read and re-validation

| Field | Value |
|---|---|
| **ID** | EXE-008 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-050–051, BR-054, ADR-019 |
| **Blocks** | EXE-011, REC-001, RCV-003, AUD-003, OBS-004, EXE-014 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

Each step runs only after the previous one is confirmed and the world still allows it.

## Scope

- After confirmation take a new snapshot
- run validate_step (PRE_STEP) then simulate (SIMULATION) for the next step
- request a new plan validation + attestation if the attestation expired
- stop and mark PartiallyCompleted on any non-ALLOW, open a review item with the primary code
- mark request Paying then Paid after PAY confirmation
- step types WITHDRAW and SUPPLY; a leading WITHDRAW in request plans

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-007: Implement the executor with outbox semantics
- CHR-003: Implement the transaction tracker
- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations
- POL-007: Simulate each step with eth_call before signing

## Acceptance criteria

- [ ] A balance change by the Owner between refill and pay is detected and handled
- [ ] The next step is not sent while the previous one is Pending

## Testing requirements

- Integration: AT-07, AT-10

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
