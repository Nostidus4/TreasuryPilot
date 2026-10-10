# [CONTRACTS] Allow refill paths between operational wallets

| Field | Value |
|---|---|
| **ID** | SC-L06 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Needs Discussion |
| **Traces to** | BR-012, FR-416 |
| **Blocks** | ENG-L01 |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-059: Refill from other operational wallets

Problem behind this work (from `docs/FEATURES.md`):

- **F-059** solves: Funds stranded in one operational wallet.

## Objective

Let O2 fund O1 when T is short.

## Scope

- Generalize path allowlist
- source buffer check for operational sources

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-009: Implement refill() bound to an approved request

## Acceptance criteria

- [ ] A mandated Oi→Oj refill succeeds and respects the source buffer

## Testing requirements

- Contract tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
