# [EXECUTION] Implement the planning pipeline task

| Field | Value |
|---|---|
| **ID** | EXE-004 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-405–413 |
| **Blocks** | WEB-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-052: Terms-aware deterministic scheduler
- F-053: AI plan proposal & explanation
- F-054: Rule-based fallback planner
- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)
- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-052** solves: P4: rules like "earliest due first" leave money on the table.
- **F-053** solves: Handles judgment cases (vendor criticality notes, ambiguous priorities, multi-constraint trade-offs) and explains them.
- **F-054** solves: Availability without granting extra authority.

## Objective

Turn eligible requests into a validated, attested plan.

## Scope

- Take snapshot
- run the engine
- request the AI proposal on the ai queue with a timeout
- score and select
- validate
- on ALLOW attest and persist plan and steps
- on NEEDS_APPROVAL or BLOCK create review items
- write audit records

## Out of scope

Execution of steps (EXE-007).

## Technical notes

Split into two PRs if needed: deterministic path first, then AI integration.

## Dependencies

- EXE-003: Implement the deadline trigger
- CHR-002: Implement block-consistent snapshots
- ENG-008: Expose plan scoring and binding-constraint reporting
- POL-006: Sign and verify plan attestations
- AGT-009: Score AI proposals and select the plan

## Acceptance criteria

- [ ] With AI disabled the pipeline produces a valid deterministic plan
- [ ] An AI timeout falls back per BR-055 and records RULE_BASED
- [ ] NEEDS_APPROVAL creates exactly one review item

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
