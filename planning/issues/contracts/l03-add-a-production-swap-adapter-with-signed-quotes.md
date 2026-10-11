# [CONTRACTS] Add a production swap adapter with signed quotes

| Field | Value |
|---|---|
| **ID** | SC-L03 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | contracts |
| **Status** | Needs Discussion |
| **Traces to** | FR-513 |
| **Blocks** | EXE-L02 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-065: Real DEX/aggregator swap with verified quotes

Problem behind this work (from `docs/FEATURES.md`):

- **F-065** solves: Real liquidity and real price protection.

## Objective

Swap through a real DEX with verified quotes.

## Scope

- Quote struct signed by an allowlisted source
- adapter verifies signature, expiry, pair and recipient

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-018: Add the test router and swapForGas

## Acceptance criteria

- [ ] Forged or expired quote reverts

## Testing requirements

- Contract + fork tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
