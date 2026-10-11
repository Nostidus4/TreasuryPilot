# [INVOICES] Implement manual request creation and editing

| Field | Value |
|---|---|
| **ID** | INV-003 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
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
- validation: vendor exists, payee belongs to the vendor and is not Deactivated, asset equals the treasury stablecoin, amount positive with ≤ asset decimals, dates valid
- bound vs free fields (M05-D6): bound edit → new revision, approvals Invalidated, flags recomputed, status Draft
- free-field edits without revision
- onchain_request_id = keccak('TP_REQ_V1', orgId, uuid)
- invoice_hash per §3
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
- [ ] A payee of another vendor returns PAYEE_NOT_OF_VENDOR
- [ ] Editing the amount of an Approved request invalidates the approval and returns it to Draft
- [ ] Editing the note does not
- [ ] A stale If-Match returns 412

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
