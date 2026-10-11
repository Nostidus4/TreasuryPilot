# [INVOICES] Implement reject, cancel, invalidation and expiry

| Field | Value |
|---|---|
| **ID** | INV-011 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-003, BR-077, FR-317, FR-320, FR-324 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-038: Invoice approval via EIP-712 signature
- F-039: Payment request lifecycle & state machine

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.
- **F-039** solves: Unambiguous status. No single "Failed" state that erases history.

## Objective

Approvals stop being valid when they should.

## Scope

- Reject (terminal) endpoint
- cancel endpoint with PAYMENT_IN_FLIGHT guard and cancel_onchain = Pending when an approval was ever Valid
- GET cancel-tx building cancelRequest(requestId) for an approver wallet or a Safe tx for the Owner
- RequestCancelled event sync → Confirmed
- periodic task (5 min) expiring approvals and requests
- renew endpoint (Expired → Draft, new revision)

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-010: Implement approval typed data and signature verification
- SC-022: Add on-chain request cancellation
- MDT-009: Build governance transactions and collect owner signatures in the app

## Acceptance criteria

- [ ] An edited approved request is no longer payable
- [ ] Cancel is refused while a payment is in flight
- [ ] A cancelled, previously approved request shows Cancel on-chain until RequestCancelled is observed
- [ ] Expired approvals are marked and require renew plus re-approval

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
