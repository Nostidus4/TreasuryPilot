# [POLICY] Validate approval, mandate and payee conditions

| Field | Value |
|---|---|
| **ID** | POL-002 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-001–005, BR-010, BR-013, BR-015, BR-066, FR-313, FR-410 |
| **Blocks** | POL-003 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.

## Objective

Deterministic checks that a step is authorized before it is attested.

## Scope

- ValidationContext model (§4.1)
- gates: pause requested, circuit open, unknown operations, coverage, snapshot freshness (≤ 30 s and ≤ 5 blocks), data missing, chain/asset match
- request and approval checks: present, typed fields equal current request (APPROVAL_STALE), signature/ERC-1271, current approver set, expiry, maker-checker with solo mode
- HIGH flags acknowledged in the approval and none raised after it (FLAG_UNACKNOWLEDGED)
- screening
- mandate lifecycle, executor
- payee active and cooling over
- plan shape checks (PLAN_MALFORMED)
- REQUEST_CANCELLED when the request is Cancelled off-chain or requestCancelled on-chain

## Out of scope

Limits, liquidity and aggregation (POL-003).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- POL-001: Define the reason-code catalogue and decision model
- ENG-010: Build EIP-712 typed data for payment approvals and attestations

## Acceptance criteria

- [ ] Each failed condition returns its specific reason code
- [ ] A failed gate skips step checks and marks them skipped
- [ ] An unacknowledged HIGH flag, or one raised after approval, yields FLAG_UNACKNOWLEDGED
- [ ] Rows 7, 8 and 11 of docs/modules/policy-engine §8.5 give the documented result

## Testing requirements

- Unit: one test per code

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
