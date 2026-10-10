# [POLICY] Validate limits, buffers, deadlines, coverage and unknown operations

| Field | Value |
|---|---|
| **ID** | POL-003 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-022, BR-030, BR-040, BR-051, BR-060, FR-411 |
| **Blocks** | POL-004, EXE-008, AGT-007, AGT-010, CMP-002 |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.

## Objective

Complete the validator so it mirrors every contract check plus the off-chain safety gates.

## Scope

- Per-request and daily limit checks using snapshot counters
- buffer after each step
- deadline feasibility
- snapshot freshness and coverage
- block if any operation is Unknown
- over-cap only → NEEDS_APPROVAL unless a granted exception exists

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

An exception never masks another failure.

## Dependencies

- POL-002: Validate approval, mandate and payee conditions

## Acceptance criteria

- [ ] Missing or stale data never yields ALLOW
- [ ] Over per-request cap alone yields NEEDS_APPROVAL
- [ ] Over cap plus over daily yields BLOCK

## Testing requirements

- Unit: decision matrix from Autonomy §4

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
