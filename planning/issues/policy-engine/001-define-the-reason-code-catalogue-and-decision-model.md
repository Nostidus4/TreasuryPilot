# [POLICY] Define the reason-code catalogue and decision model

| Field | Value |
|---|---|
| **ID** | POL-001 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-057, API_SPEC §9 |
| **Blocks** | POL-002 |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.

## Objective

One list of reason codes shared by the validator, API errors, UI and contract errors.

## Scope

- Enum of reason codes with severity and default decision (ALLOW / NEEDS_APPROVAL / BLOCK)
- Decision model {decision, reasonCodes, checks}
- docs table generated from the enum

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Names must match contract custom errors where one exists.

## Dependencies

- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] Every code in API_SPEC §9 exists in the enum
- [ ] A test fails if a contract error has no matching code

## Testing requirements

- Unit: catalogue consistency test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
