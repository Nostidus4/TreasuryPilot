# [TREASURY] Implement the asset registry with on-chain decimals check

| Field | Value |
|---|---|
| **ID** | TRS-003 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-083, FR-108 |
| **Blocks** | TRS-004 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-013: Asset registry

Problem behind this work (from `docs/FEATURES.md`):

- **F-013** solves: Prevents token impersonation and decimal errors.

## Objective

Assets are identified by chain and address, with verified decimals.

## Scope

- Seed assets from config
- verify decimals() on-chain when adding
- is_test flag
- GET /chains

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-002: Load and validate platform chain configuration
- CHR-001: Build the RPC client with failover

## Acceptance criteria

- [ ] A decimals mismatch refuses the asset
- [ ] Test assets are returned with isTest true

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
