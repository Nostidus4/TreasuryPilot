# [POLICY] Sign and verify plan attestations

| Field | Value |
|---|---|
| **ID** | POL-006 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-059, FR-412–413, ADR-006 |
| **Blocks** | EXE-004, EXE-005 |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-056: Plan attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-056** solves: Prevents the payload being altered between validation and execution (plan drift).

## Objective

Only validator-approved plans can reach the signer.

## Scope

- attest(plan, decision) using the policy key (loaded only in the core worker)
- verify_attestation helper for the signer service
- nonce and validUntil handling

## Out of scope

On-chain verification (SC-L04).

## Technical notes

The policy key is distinct from the executor key.

## Dependencies

- POL-005: Define canonical plan encoding and planHash

## Acceptance criteria

- [ ] An attestation over a modified plan fails verification
- [ ] Expired attestations fail
- [ ] Nonce reuse is rejected

## Testing requirements

- Unit: attestation tests

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
