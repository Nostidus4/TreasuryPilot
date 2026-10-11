# [INVOICES] Implement approval typed data and signature verification

| Field | Value |
|---|---|
| **ID** | INV-010 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-003–BR-007, FR-316–318, M05-D1 |
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

- GET approval-typed-data built server-side from the current revision (11 fields, expiry = min(deadline + 14 d, now + approvalMaxAge))
- POST approve with {signature, revision} running docs/modules/invoices §8.6 steps 1–8 (revision, linked wallet, maker-checker/solo mode, HIGH flags acked, rebuild, ECDSA or ERC-1271, on-chain approver set, store with acknowledged_flag_ids)
- transition to Approved
- Idempotency-Key

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- INV-009: Implement submit-for-approval and flag acknowledgment
- ENG-010: Build EIP-712 typed data for payment approvals and attestations
- IDN-008: Implement the maker-checker service and solo mode

## Acceptance criteria

- [ ] A signature over a client-modified message is rejected
- [ ] A stale revision returns REVISION_CHANGED
- [ ] Creator approving returns MAKER_CHECKER unless solo mode, which is recorded
- [ ] A signer not in the on-chain approver set returns NOT_IN_APPROVER_SET
- [ ] An ERC-1271 mock wallet can approve

## Testing requirements

- Integration with test keys

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
