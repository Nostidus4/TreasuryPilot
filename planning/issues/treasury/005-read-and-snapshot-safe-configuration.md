# [TREASURY] Read and snapshot Safe configuration

| Field | Value |
|---|---|
| **ID** | TRS-005 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-103, FR-105 |
| **Blocks** | TRS-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-011: Safe smart-account connection

Problem behind this work (from `docs/FEATURES.md`):

- **F-011** solves: Enforcement is only real if every wallet in scope supports the control path. A backend check in front of an EOA is not enforcement (Domain §6.2).

## Objective

Know each Safe's owners, threshold, modules and guard at a block.

## Scope

- Reader for owners, threshold, enabled modules (paginated), guard
- store safe_config_snapshots
- periodic refresh task
- diff detection emits an event

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] Snapshot matches on-chain values
- [ ] A changed owner set produces a change event within one polling interval

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
