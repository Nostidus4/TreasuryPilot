# [ADMIN] Add subscriptions and customer invoicing

| Field | Value |
|---|---|
| **ID** | ADM-L03 |
| **Epic** | M18 · Platform Admin & Billing |
| **Module** | `admin` ([spec](../../../docs/modules/admin/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-926, BR-091 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Platform Admin & Billing**. It supports:

- F-152: Billing & subscriptions

Problem behind this work (from `docs/FEATURES.md`):

- **F-152** solves: Commercialization.

## Objective

Charge customers.

## Scope

- Plans
- invoices
- payment collection outside customer treasuries

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ADM-L02: Meter usage for billing

## Acceptance criteria

- [ ] No fee is ever deducted from a customer treasury

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
