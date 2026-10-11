# [DOMAIN] Decide the M1 stablecoin (owner: Phúc)

| Field | Value |
|---|---|
| **ID** | DOM-002 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | OQ-03, ADR-012 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-013: Asset registry

Problem behind this work (from `docs/FEATURES.md`):

- **F-013** solves: Prevents token impersonation and decimal errors.

## Objective

Choose the token for the demo and for automated runs.

## Scope

- Check faucet limits against ~40 runs
- decide between Circle testnet USDC, team TestUSDC or both
- record token addresses

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Recommendation: both.

## Dependencies

- DOM-001: Decide the M1 chain (owner: Phúc)

## Acceptance criteria

- [ ] ADR-012 lists the token address(es) and how to obtain funds
- [ ] Faucet limits are documented

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
