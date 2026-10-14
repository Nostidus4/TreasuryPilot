# [ENGINE] Add FX conversion and depeg checks for fiat invoices

| Field | Value |
|---|---|
| **ID** | ENG-L02 |
| **Epic** | M07 · Financial Engine (py-core) |
| **Module** | `financial-engine` ([spec](../../../docs/modules/financial-engine/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-322 |
| **Blocks** | — |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Financial Engine (py-core)**. It supports:

- F-041: Fiat-denominated invoices with FX & depeg checks

Problem behind this work (from `docs/FEATURES.md`):

- **F-041** solves: Real invoices are usually fiat-denominated.

## Objective

Parent ticket for the fiat FX safety work; keep unscheduled until ENG-015 and ENG-016 are estimated and complete.

## Scope

- Track the two child tickets: ENG-015 models immutable fiat approvals, rational FX rates, quotes and source/depeg policy (S, ≤0.5 day)
- ENG-016 implements fail-closed quote validation, exact conversion and the approved maximum guard with boundary/property tests (S, ≤0.5 day)

## Out of scope

Invoice storage, approval signing and payment orchestration (INV-L04)

## Technical notes

Split before scheduling: deliver the pure models first, then the pure conversion/check function. Child work totals S + S (≤1 day); preserve this accepted parent as the traceability link for FR-322.

## Dependencies

- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] Never proposes more than the approved maximum stablecoin amount
- [ ] Stale, mismatched, out-of-tolerance or depegged quotes are blocked

## Testing requirements

- Unit + property

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
