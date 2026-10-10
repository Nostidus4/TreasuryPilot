# [CONTRACTS] Register the attestation schema and add an attest helper

| Field | Value |
|---|---|
| **ID** | SC-019 |
| **Epic** | M04 · Smart Contracts |
| **Module** | `contracts` ([spec](../../../docs/modules/contracts/README.md)) |
| **Phase / Priority** | M1 / P2 |
| **Size** | S (≤ 0.5 day) |
| **Area** | contracts |
| **Status** | Ready for Review |
| **Traces to** | FR-608 |
| **Blocks** | REC-005 |

## Context

This ticket belongs to the epic **Smart Contracts**. It supports:

- F-074: On-chain payment attestation

Problem behind this work (from `docs/FEATURES.md`):

- **F-074** solves: Third-party-verifiable proof of payment (helps the on-chain bonus).

## Objective

Publish a verifiable on-chain record for each paid request.

## Scope

- EAS schema {fingerprintHash, requestId, payTxHash, amount, payee, timestamp}
- script to register it
- helper used by the worker

## Out of scope

Worker integration (REC-005).

## Technical notes

Only if EAS exists on the chosen chain; otherwise close as not applicable.

## Dependencies

- DOM-001: Decide the M1 chain (owner: Phúc)

## Acceptance criteria

- [ ] Schema UID recorded in the deployments manifest
- [ ] A sample attestation resolves on the explorer

## Testing requirements

- Integration: testnet smoke

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
