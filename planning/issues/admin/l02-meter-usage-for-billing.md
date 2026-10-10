# [ADMIN] Meter usage for billing

| Field | Value |
|---|---|
| **ID** | ADM-L02 |
| **Epic** | M18 · Platform Admin & Billing |
| **Module** | `admin` ([spec](../../../docs/modules/admin/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Needs Discussion |
| **Traces to** | FR-926 |
| **Blocks** | ADM-L03 |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Platform Admin & Billing**. It supports:

- F-152: Billing & subscriptions

Problem behind this work (from `docs/FEATURES.md`):

- **F-152** solves: Commercialization.

## Objective

Usage numbers per org.

## Scope

- Metering from events (paid requests, volume)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- OBS-004: Compute operational metrics

## Acceptance criteria

- [ ] Usage reconciles with the event store

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
