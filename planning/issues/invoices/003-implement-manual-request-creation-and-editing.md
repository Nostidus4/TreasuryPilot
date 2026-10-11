# [INVOICES] Implement manual request creation and editing

| Field | Value |
|---|---|
| **ID** | INV-003 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | FR-301–302, BR-073 |
| **Blocks** | DEV-006, INV-004, INV-005, INV-006, INV-008, INV-L02, INV-L03, INV-L04, WEB-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-030: Manual invoice entry

Problem behind this work (from `docs/FEATURES.md`):

- **F-030** solves: The baseline intake channel.

## Objective

Operators can enter and edit invoices with strict validation.

## Scope

- POST /requests and PATCH with If-Match
- validation: payee exists, asset equals the treasury stablecoin, amount precision
- revisions on edit
- creator and last editor recorded
- Idempotency-Key

## Out of scope

Fingerprint and anomaly checks (INV-006, INV-007).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-002: Implement the request state machine
- MDT-004: Implement vendor and payee proposals with screening

## Acceptance criteria

- [ ] Wrong asset returns ASSET_NOT_PAYMENT_STABLECOIN
- [ ] Editing creates a new revision
- [ ] A stale If-Match returns 412

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
