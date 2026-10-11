# [INVOICES] Implement submit-for-approval and flag acknowledgment

| Field | Value |
|---|---|
| **ID** | INV-009 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-313 |
| **Blocks** | INV-010 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-036: Anomaly & fraud-signal detection
- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-036** solves: BEC fraud, duplicate payment, prompt injection (P3).
- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

A draft becomes approvable only when it is clean or its flags are acknowledged.

## Scope

- POST /submit (Draft → AwaitingApproval) with checks: no duplicate, terms confirmed or none, payee exists
- POST /flags/{id}/ack by an Approver

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-007: Implement deterministic anomaly checks
- INV-008: Implement payment-terms confirmation

## Acceptance criteria

- [ ] Submit is refused with unconfirmed extracted terms
- [ ] High flags must be acknowledged before the typed-data endpoint will serve

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
