# [DOMAIN] Verify Ethereum Sepolia infrastructure (owner: Nostidus4)

| Field | Value |
|---|---|
| **ID** | DOM-001 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Assignment |
| **Traces to** | OQ-02, ADR-012, PH-1 |
| **Blocks** | DEV-010, SC-016, SC-019, DOM-002 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-010: Treasury creation
- F-151: Platform configuration (chains, RPC, assets)

Problem behind this work (from `docs/FEATURES.md`):

- **F-010** solves: Defines the scope of the money the agent manages.
- **F-151** solves: Removes hard-coded network values.

## Objective

Confirm that everything the build assumes exists on Ethereum Sepolia and record it.

## Scope

- Verify Safe v1.4.1 singleton, proxy factory, MultiSendCallOnly and fallback handler addresses
- Safe Transaction Service endpoint
- EAS and SchemaRegistry addresses
- Alchemy + public RPC endpoints
- Etherscan API key for verification
- update ADR-012 and the deployments manifest template

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Decision taken 2026-10-11 (PH-1): Ethereum Sepolia. This ticket now records the verification. Ownership transferred on 2026-10-14 from longhuynh55 (Phuc) to Nostidus4 (Tan), the repository owner responsible for the project's infrastructure access. Nostidus4 owns RPC/API/service configuration, infrastructure verification and recording the Safe transaction evidence; longhuynh55 supports contract integration. The acceptance criteria and deployment dependencies remain unchanged.

## Dependencies

- None

## Acceptance criteria

- [ ] ADR-012 lists every address with a link
- [ ] A test Safe transaction on Sepolia is recorded
- [ ] Both RPC endpoints answer eth_chainId = 11155111

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
