# [DOMAIN] Set up tUSDC and the Circle USDC evidence run (owner: Phúc)

| Field | Value |
|---|---|
| **ID** | DOM-002 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Assignment |
| **Traces to** | OQ-03, OQ-05, ADR-012, PH-2, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-013: Asset registry

Problem behind this work (from `docs/FEATURES.md`):

- **F-013** solves: Prevents token impersonation and decimal errors.

## Objective

Have the tokens and funds ready for the demo and the real-token evidence run.

## Scope

- tUSDC (6 decimals, label TEST) deployment parameters
- Circle USDC Sepolia address verified
- collect Circle faucet funds (developer console) for one run with limits ÷ 100
- document the scaled mandate values
- collect Aave Sepolia test USDC from the Aave faucet for the treasury; Circle run stays PAY-only

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Decision taken 2026-10-11 (PH-2).

## Dependencies

- DOM-001: Verify Ethereum Sepolia infrastructure (owner: Phúc)

## Acceptance criteria

- [ ] ADR-012 lists both token addresses
- [ ] At least 120 Circle USDC are available on the demo treasury before the evidence run
- [ ] The scaled mandate config is in the demo runbook

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
