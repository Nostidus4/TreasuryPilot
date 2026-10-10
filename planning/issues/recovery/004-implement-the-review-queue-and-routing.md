# [RECOVERY] Implement the review queue and routing

| Field | Value |
|---|---|
| **ID** | RCV-004 |
| **Epic** | M12 · Recovery & Exceptions |
| **Module** | `recovery` ([spec](../../../docs/modules/recovery/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-704–705 |
| **Blocks** | WEB-013 |

## Context

This ticket belongs to the epic **Recovery & Exceptions**. It supports:

- F-082: Needs-review queue & exception routing

Problem behind this work (from `docs/FEATURES.md`):

- **F-082** solves: Exceptions never disappear and are never "auto-fixed" by loosening policy.

## Objective

Every stop becomes one actionable item for the right role.

## Scope

- review_items schema
- creation rules per outcome type
- routing table (over-cap → Owner, payee/budget → Owner policy edit, amount/payee → re-approval, infra → Operator)
- list and action endpoints
- SLA due time

## Out of scope

UI (WEB-013).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-002: Implement the request state machine

## Acceptance criteria

- [ ] Each non-ALLOW outcome creates exactly one open item
- [ ] Acting on a stale item returns STALE_ITEM
- [ ] Only the routed role can act

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
