# [MANDATE] Validate mandate drafts and generate summary and diff

| Field | Value |
|---|---|
| **ID** | MDT-002 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-014, FR-201–203 |
| **Blocks** | MDT-003, MDT-L01 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-020: Mandate configuration

Problem behind this work (from `docs/FEATURES.md`):

- **F-020** solves: Turns "trust the agent" into an explicit, enforceable, auditable grant (P2).

## Objective

Owners see exactly what they are about to authorize.

## Scope

- POST /mandates creating a draft
- validation per docs/modules/mandate §8.1
- human summary in display and base units
- diff against the active version with looser/stricter markers (§8.2)
- bundle preview (§8.3)
- clone and discard

## Out of scope

Activation (MDT-003).

## Technical notes

Only the Owner role may call it.

## Dependencies

- MDT-001: Create mandate, payee and exception schema
- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] Incomplete drafts return MANDATE_INCOMPLETE with the missing fields
- [ ] target < buffer returns TARGET_BELOW_BUFFER
- [ ] Summary amounts equal the config in base units
- [ ] A higher limit is marked looser and requires confirmation

## Testing requirements

- Unit + integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
