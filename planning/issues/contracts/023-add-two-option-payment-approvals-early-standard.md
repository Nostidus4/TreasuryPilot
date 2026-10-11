# [CONTRACTS] Add two-option payment approvals (early / standard)

| Field | Value |
|---|---|
| **ID** | SC-023 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-024, FR-524, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

The approved discount is actually captured on-chain: the module pays exactly the early amount before its date, otherwise the standard amount.

## Scope

- PaymentApproval fields earlyAmount and earlyPayBy
- payAmount selection in pay()
- counters, buffer and daily checks on payAmount
- WrongPaymentOption
- PaymentExecuted(early flag)

## Out of scope

Off-chain derivation of the early amount (INV-008).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- SC-006: Implement pay() core flow
- SC-005: Implement approval signature verification

## Acceptance criteria

- [ ] Before earlyPayBy the payee receives exactly earlyAmount
- [ ] After it, exactly amount
- [ ] earlyAmount > amount reverts
- [ ] earlyAmount = 0 behaves like a single-option approval

## Testing requirements

- Unit + fuzz on the time boundary

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
