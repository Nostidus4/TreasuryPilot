# [INVOICES] Implement approval typed data and signature verification

| Field | Value |
|---|---|
| **ID** | INV-010 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-003–BR-005, FR-316–317 |
| **Blocks** | MDT-006, INV-011, EXE-003, WEB-009 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-038: Invoice approval via EIP-712 signature

Problem behind this work (from `docs/FEATURES.md`):

- **F-038** solves: Approval is cryptographic and bound to exact fields, not a backend flag.

## Objective

Approvers sign exactly the fields the contract will check.

## Scope

- GET approval-typed-data
- POST approve verifying the signature, the approver's linked wallet, membership in the on-chain approver set and maker-checker
- store approval
- transition to Approved
- Idempotency-Key

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-009: Implement submit-for-approval and flag acknowledgment
- ENG-010: Build EIP-712 typed data for approvals, exceptions and attestations
- IDN-008: Implement the maker-checker service and solo mode

## Acceptance criteria

- [ ] A signature over different fields is rejected
- [ ] Creator approving returns MAKER_CHECKER
- [ ] A signer not in the on-chain approver set returns NOT_IN_APPROVER_SET

## Testing requirements

- Integration with test keys

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
