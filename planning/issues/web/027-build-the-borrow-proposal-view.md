# [WEB] Build the borrow proposal view

| Field | Value |
|---|---|
| **ID** | WEB-027 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-522, ADR-019 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-069: Borrow proposal (cost vs withdraw, health factor)

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

Let the Owner compare withdraw vs borrow (D6).

## Scope

- Proposal card: amount, cost to repayment, withdraw cost, health factor before/after, reason
- clear 'no transaction without owner authorization'

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-026: Build the treasury position card
- ENG-014: Build the borrow proposal

## Acceptance criteria

- [ ] A proposal is displayed with engine numbers and no sign button in M1 (P2 adds signing)

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
