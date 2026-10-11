# [COMPLIANCE] Build the screening adapter and fixture provider

| Field | Value |
|---|---|
| **ID** | CMP-001 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | BR-085, FR-906, NFR-CMP-04 |
| **Blocks** | MDT-004, CMP-002, CMP-L01 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-110: Payee sanctions / blocklist screening

Problem behind this work (from `docs/FEATURES.md`):

- **F-110** solves: Paying sanctioned or known-malicious addresses.

## Objective

Screen addresses through a replaceable provider.

## Scope

- Adapter interface screen(address)
- fixture provider reading a labelled TEST list (sample from a public sanctions list plus custom entries)
- screenings records with TTL

## Out of scope

A commercial provider (Later).

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-001: Create mandate, payee and exception schema

## Acceptance criteria

- [ ] A listed address returns HIT
- [ ] Provider error returns ERROR and callers fail closed
- [ ] Fixture data is labelled TEST DATA

## Testing requirements

- Unit

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
