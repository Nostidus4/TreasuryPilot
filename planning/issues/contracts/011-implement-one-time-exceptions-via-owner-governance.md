# [CONTRACTS] Implement one-time exceptions via owner governance

| Field | Value |
|---|---|
| **ID** | SC-011 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | contracts |
| **Status** | Ready for Assignment |
| **Traces to** | BR-040–BR-043, FR-216–217 |
| **Blocks** | — |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-025: One-time exception

Problem behind this work (from `docs/FEATURES.md`):

- **F-025** solves: Occasional large payments without loosening the general mandate.

## Objective

Let the Owner authorize one over-cap payment without loosening anything else.

## Scope

- grantException(requestId, amount, payee, expiry) and revokeException callable only by Safe T
- store the current mandate version
- pay() accepts over-cap only with an unused, unexpired exception matching amount, payee and version
- mark used atomically
- ExceptionGranted/Revoked events

## Out of scope

Any lifting of the daily cap, buffer or payee rules.

## Technical notes

M04-D3: no EIP-712 signature; the Owner signs a Safe transaction, so Safe thresholds apply automatically.

## Dependencies

- SC-007: Implement per-request limits and UTC daily counters

## Acceptance criteria

- [ ] An over-cap pay with a matching exception succeeds once
- [ ] A second use, a different request, a different payee or amount, an expired exception, or one from an older mandate version all revert
- [ ] The daily cap still blocks an exception payment that would exceed it

## Testing requirements

- Unit: AT-11 matrix

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
