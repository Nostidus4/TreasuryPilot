# [POLICY] Simulate each step with eth_call before signing

| Field | Value |
|---|---|
| **ID** | POL-007 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-067, FR-505, ADR-016, M08-D5 |
| **Blocks** | EXE-005, EXE-008 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)
- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.
- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

Catch any validator/contract drift on fresh state before a transaction is signed.

## Scope

- simulate(step, ctx): build the exact module.refill/pay calldata the signer will send
- eth_call from the executor address at block latest
- decode a revert into a reason code via decode_revert
- RPC failure → SIMULATION_UNAVAILABLE
- store a validations row with stage SIMULATION

## Out of scope

Signer-side simulation (EXE-005 keeps its own).

## Technical notes

Any revert or RPC error is BLOCK. Never retried into ALLOW within the same cycle.

## Dependencies

- POL-003: Validate limits, buffers, deadlines, coverage and unknown operations
- POL-001: Define the reason-code catalogue and decision model
- CHR-002: Implement block-consistent snapshots
- SC-016: Write deployment scripts and the deployments manifest

## Acceptance criteria

- [ ] A step that the contract would reject is BLOCKed with SIMULATION_REVERTED and the decoded code
- [ ] An unreachable RPC yields SIMULATION_UNAVAILABLE and BLOCK
- [ ] Example 12 of docs/modules/policy-engine §8.5 behaves as documented

## Testing requirements

- Integration on Anvil: one case per module error

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
