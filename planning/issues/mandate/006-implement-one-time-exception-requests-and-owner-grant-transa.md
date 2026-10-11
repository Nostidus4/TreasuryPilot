# [MANDATE] Implement one-time exception requests and owner grant transactions

| Field | Value |
|---|---|
| **ID** | MDT-006 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-040–BR-043, FR-216 |
| **Blocks** | AGT-011, WEB-013 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-025: One-time exception

Problem behind this work (from `docs/FEATURES.md`):

- **F-025** solves: Occasional large payments without loosening the general mandate.

## Objective

Owners can grant an exception for one over-cap request, with full context.

## Scope

- GET exception request (numbers from the engine, AI draft if present)
- endpoint building the Safe T transaction grantException(requestId, amount, payee, expiry)
- track ExceptionGranted event → status Granted
- reject endpoint
- pre-check that the daily limit would still hold

## Out of scope

AI draft text (AGT-011); on-chain consumption (SC-011).

## Technical notes

M04-D3: no EIP-712 exception signature.

## Dependencies

- MDT-003: Implement mandate activation and read-back
- ENG-010: Build EIP-712 typed data for approvals, exceptions and attestations
- INV-010: Implement approval typed data and signature verification

## Acceptance criteria

- [ ] The built Safe transaction grants exactly the request's amount and payee
- [ ] After the Owner executes it, status becomes Granted from the on-chain event
- [ ] A request that is not over-cap returns NOT_OVER_CAP
- [ ] If the daily limit would be exceeded the grant is refused before building the transaction

## Testing requirements

- Integration

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
