# [MANDATE] Set up the Guardian Safe with the sentinel

| Field | Value |
|---|---|
| **ID** | MDT-010 |
| **Epic** | M03 · Mandate, Payees, Exceptions & Pause |
| **Module** | `mandate` ([spec](../../../docs/modules/mandate/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-068, ADR-017, M03-D2, PH-4 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Mandate, Payees, Exceptions & Pause**. It supports:

- F-026: Pause, resume & revoke
- F-027: Circuit breaker (auto-pause)

Problem behind this work (from `docs/FEATURES.md`):

- **F-026** solves: Emergency stop.
- **F-027** solves: Limits damage from bugs or compromise between human checks.

## Objective

Each treasury gets a guardian that can stop the agent on-chain within about one block.

## Scope

- Setup step building the Guardian Safe deployment (threshold 1, owners = human guardian(s) + sentinel address from the signer)
- record guardian_setups
- mandate guardian field defaults to this Safe
- health check that the sentinel is an owner and has gas

## Out of scope

Circuit-breaker rules (RCV-006).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-009: Build governance transactions and collect owner signatures in the app
- EXE-013: Add the pause-only sentinel to the signer
- TRS-006: Build the module deploy-and-enable Safe transaction

## Acceptance criteria

- [ ] The guardian in the active mandate equals the Guardian Safe
- [ ] The sentinel can pause through it
- [ ] A human guardian can also pause from their wallet
- [ ] Removing the sentinel from the Guardian Safe disables automatic on-chain pause and shows a warning

## Testing requirements

- Integration on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
