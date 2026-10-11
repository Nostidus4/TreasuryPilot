# [COMPLIANCE] Add Travel Rule support

| Field | Value |
|---|---|
| **ID** | CMP-L02 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-908 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-112: Travel Rule support

Problem behind this work (from `docs/FEATURES.md`):

- **F-112** solves: Regulatory requirement in some jurisdictions.

## Objective

Travel Rule data exchange.

## Scope

- Provider adapter
- threshold rules

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-L01: Integrate a KYB provider

## Acceptance criteria

- [ ] Qualifying transfers hold until the exchange completes

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
