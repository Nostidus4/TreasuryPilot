# [COMPLIANCE] Integrate a KYB provider

| Field | Value |
|---|---|
| **ID** | CMP-L01 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-907 |
| **Blocks** | CMP-L02 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-111: KYB onboarding

Problem behind this work (from `docs/FEATURES.md`):

- **F-111** solves: Regulatory onboarding.

## Objective

Business verification.

## Scope

- KYB adapter
- status gates mainnet activation

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- CMP-001: Build the screening adapter and fixture provider

## Acceptance criteria

- [ ] Mainnet treasury cannot activate without KYB approval

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
