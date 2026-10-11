# [ENGINE] Build the borrow proposal

| Field | Value |
|---|---|
| **ID** | ENG-014 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-044, FR-522, ADR-019 |
| **Blocks** | WEB-027 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-069: Borrow proposal (cost vs withdraw, health factor)

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

Show when borrowing would beat withdrawing, without ever executing it.

## Scope

- propose_borrow: amount, cost to repayment, withdraw cost, health factor before/after, reason
- excluded from executable plans

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- ENG-013: Implement reserve formulas and the liquidity decision

## Acceptance criteria

- [ ] A proposal is produced when pool liquidity is insufficient
- [ ] No plan ever contains BORROW without an authorization

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
