# [EXECUTION] Build the signer service

| Field | Value |
|---|---|
| **ID** | EXE-005 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-092, ADR-006, FR-507 |
| **Blocks** | EXE-006, EXE-007, EXE-L01 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

The only component that can sign executor transactions, and only for attested steps.

## Scope

- FastAPI service with POST /sign-and-send and GET /health
- verify attestation per docs/modules/policy-engine §6.3 (trusted signer, validUntil, chain/module, recomputed planHash, payload equals step seq, nonce/step use)
- own `signer` schema with attestation_uses (only the signer DB role can write)
- same payload may be re-signed for gas replacement
- simulate (eth_call) then sign and broadcast
- shared-secret auth on the internal network

## Out of scope

KMS (EXE-L01).

## Technical notes

M08-D9: writes only to its own schema. No other endpoints.

## Dependencies

- POL-006: Sign and verify EIP-712 plan attestations with the policy key
- POL-007: Simulate each step with eth_call before signing
- SC-016: Write deployment scripts and the deployments manifest

## Acceptance criteria

- [ ] A payload that differs from the attested step is refused with PAYLOAD_MISMATCH
- [ ] A nonce reused with another planHash is refused NONCE_REUSED
- [ ] A reverted simulation is not broadcast
- [ ] Re-signing the same step payload for a replacement is allowed
- [ ] A non-allowlisted chain id is refused

## Testing requirements

- Unit + integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
