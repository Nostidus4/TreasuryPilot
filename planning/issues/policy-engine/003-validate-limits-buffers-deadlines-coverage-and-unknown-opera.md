# [POLICY] Validate limits, buffers, deadlines, coverage and unknown operations

| Field | Value |
|---|---|
| **ID** | POL-003 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-022, BR-030, BR-036, BR-040–042, BR-051, BR-060, FR-411, ADR-019 |
| **Blocks** | POL-004, EXE-008, AGT-007, AGT-010, CMP-002, POL-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.

## Objective

Complete the validator so it mirrors every contract check plus the off-chain safety gates.

## Scope

- REFILL checks mirroring M04 refill 1–9 and PAY checks mirroring pay 1–9
- PLAN stage projects state after earlier steps
- exception matching read from chain state (M08-D12)
- aggregation per §8.2 (BLOCK > NEEDS_APPROVAL > ALLOW, primary by precedence)
- warnings DEADLINE_MISSED / DISCOUNT_MISSED
- validate_plan and validate_step entry points
- SUPPLY/WITHDRAW step checks and PaymentReserve intact after SUPPLY (docs/modules/policy-engine §15)
- PAY amount must equal the early or standard option for the expected execution time

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

An exception never masks another failure.

## Dependencies

- POL-002: Validate approval, mandate and payee conditions

## Acceptance criteria

- [ ] Rows 1–6, 9 and 10 of docs/modules/policy-engine §8.5 give the documented decision and primary code
- [ ] Missing or stale data never yields ALLOW
- [ ] An exception removes only OVER_PER_REQUEST_LIMIT
- [ ] A late payment that passes all checks is ALLOW with DEADLINE_MISSED
- [ ] A SUPPLY that would cut into PaymentReserve is BLOCKed with RESERVE_BREACH

## Testing requirements

- Unit: decision matrix §8.5
- property: dropping or staling any input never yields ALLOW, exception never masks a hard failure

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
