# [WEB] Build the exception and review console

| Field | Value |
|---|---|
| **ID** | WEB-013 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-920 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-135: Exception & review console

Problem behind this work (from `docs/FEATURES.md`):

- **F-135** solves: Humans resolve exceptions quickly and correctly.

## Objective

Resolve stops quickly with the right action per role.

## Scope

- Review queue by type, routed role and SLA (incl. FEE_APPROVAL, UNEXPECTED_OUTFLOW, UNCERTAIN_TX)
- detail with reason codes and completed steps
- exception request view with AI draft and engine numbers, Owner creates the grantException governance tx (no EIP-712)
- allowed actions per routing table (docs/modules/recovery §8.3)
- stale-item handling

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-011: Build plan cards and the Why panel
- RCV-004: Implement the review queue and routing
- MDT-006: Implement one-time exception requests and owner grant transactions
- WEB-025: Build the governance signing inbox

## Acceptance criteria

- [ ] An over-cap request shows the Owner a signable exception
- [ ] After the grant and execution the item closes
- [ ] Acting on a stale item prompts a refresh

## Testing requirements

- E2E on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
