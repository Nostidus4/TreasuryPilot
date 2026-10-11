# [AGENT] Extract and validate payment terms

| Field | Value |
|---|---|
| **ID** | AGT-005 |
| **Epic** | M09 · AI Agent |
| **Module** | `agent` ([spec](../../../docs/modules/agent/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | ai |
| **Status** | Ready for Assignment |
| **Traces to** | FR-310 |
| **Blocks** | AGT-013, WEB-008 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **AI Agent**. It supports:

- F-035: Payment-terms extraction

Problem behind this work (from `docs/FEATURES.md`):

- **F-035** solves: Terms drive the value of the scheduler (P4).

## Objective

Find discount, due-date and late-fee terms in invoice text.

## Scope

- Terms sub-schema in the extraction
- validation through the ENG-005 model
- uncertain flag when ambiguous
- store as unconfirmed

## Out of scope

Confirmation endpoint (INV-008).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- AGT-004: Implement invoice extraction
- ENG-005: Model payment terms and their value function

## Acceptance criteria

- [ ] '2/10 net 30' is parsed into the right structure
- [ ] Ambiguous text sets uncertain and requires a human choice

## Testing requirements

- Unit with recorded responses

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
