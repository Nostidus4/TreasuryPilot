# [POLICY] Define the reason-code catalogue and decision model

| Field | Value |
|---|---|
| **ID** | POL-001 |
| **Epic** | M08 · Policy Engine & Attestation |
| **Module** | `policy-engine` ([spec](../../../docs/modules/policy-engine/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-057, API_SPEC §9, ADR-019 |
| **Blocks** | POL-002, POL-007 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Policy Engine & Attestation**. It supports:

- F-055: Policy validation (ALLOW / NEEDS_APPROVAL / BLOCK)

Problem behind this work (from `docs/FEATURES.md`):

- **F-055** solves: A single, auditable gate that mirrors the contract checks.

## Objective

One list of reason codes shared by the validator, API errors, UI and contract errors.

## Scope

- ReasonCode enum per docs/modules/policy-engine §6.4 (group, precedence, default decision, contract error, BR)
- warning codes DEADLINE_MISSED, DISCOUNT_MISSED, TARGET_NOT_REACHED
- Decision and Check models per §4.1 (decision, primary, codes, warnings, checks, stage, step_seq, policy_version, snapshot_block)
- decode_revert(selector) → code
- docs table generated from the enum
- reason codes SUPPLY_FLOOR_BREACH, OVER_SUPPLY_PER_TX, OVER_SUPPLY_DAILY, RESERVE_BREACH, BELOW_MIN_SUPPLY (warning), INSUFFICIENT_POOL_LIQUIDITY, INSUFFICIENT_A_TOKEN, ALLOWANCE_NOT_CLEARED, WRONG_PAYMENT_OPTION, BORROW_NOT_AUTHORIZED, HEALTH_FACTOR_TOO_LOW

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Names must match contract custom errors where one exists.

## Dependencies

- ENG-001: Create py-core money types and domain models

## Acceptance criteria

- [ ] Every code in API_SPEC §9 exists in the enum
- [ ] A test fails if a module custom error (M04 §6.4) has no matching code
- [ ] decode_revert maps every module error selector
- [ ] Precedence order matches §6.4 group order

## Testing requirements

- Unit: catalogue consistency test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
