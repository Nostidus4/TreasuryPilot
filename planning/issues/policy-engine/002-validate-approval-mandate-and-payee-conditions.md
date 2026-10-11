# [POLICY] Validate approval, mandate and payee conditions

| Field | Value |
|---|---|
| **ID** | POL-002 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-001, BR-010, BR-013, BR-015, FR-410 |
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

- Checks: approval valid for the current revision and approver set, not expired
- mandate active, not paused, not expired, version matches
- payee active and cooling over
- action and path allowed

## Out of scope

Limits and liquidity (POL-003).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- POL-001: Define the reason-code catalogue and decision model
- ENG-010: Build EIP-712 typed data for approvals, exceptions and attestations

## Acceptance criteria

- [ ] Each failed condition returns its specific reason code
- [ ] Multiple failures return all codes with the most restrictive decision

## Testing requirements

- Unit: one test per code

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
