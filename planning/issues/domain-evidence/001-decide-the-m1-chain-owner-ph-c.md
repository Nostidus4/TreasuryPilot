# [DOMAIN] Decide the M1 chain (owner: Phúc)

| Field | Value |
|---|---|
| **ID** | DOM-001 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | OQ-02, ADR-012 |
| **Blocks** | DEV-010, SC-019, DOM-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-010: Treasury creation
- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-010** solves: Defines the scope of the money the agent manages.
- **F-151** solves: Removes hard-coded network values.

## Objective

Choose the testnet and record the evidence for the choice.

## Scope

- Verify on the candidate chain: Safe deployments and safe-eth-py support, stablecoin faucet, EAS, two RPC providers, explorer
- update ADR-012 with the decision and links

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Recommendation: Base Sepolia; fallback Ethereum Sepolia.

## Dependencies

- None

## Acceptance criteria

- [ ] ADR-012 is Accepted with the chain id and verification links
- [ ] A short test transaction through a Safe on that chain is recorded

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
