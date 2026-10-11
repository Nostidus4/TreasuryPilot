# [COMPLIANCE] Implement data classification, encryption helpers and log redaction

| Field | Value |
|---|---|
| **ID** | CMP-003 |
| **Epic** | M14 · Compliance |
| **Module** | `compliance` ([spec](../../../docs/modules/compliance/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | BR-074, FR-909, NFR-PRIV-01–04 |
| **Blocks** | CMP-L03, OBS-001 |
| **Submission cut** | B |

## Context

This ticket belongs to the epic **Compliance**. It supports:

- F-113: Data minimization

Problem behind this work (from `docs/FEATURES.md`):

- **F-113** solves: Privacy, and immutability risks on-chain.

## Objective

Sensitive data is protected by default.

## Scope

- Field classification constants
- encrypt/decrypt helper for Confidential columns
- structlog redaction processors (emails, document text, tokens, signatures)
- test scanning sample logs

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- DEV-001: Initialize monorepo skeleton

## Acceptance criteria

- [ ] A log line containing an email or signature is redacted
- [ ] Confidential columns are unreadable in a raw DB dump

## Testing requirements

- Unit + security

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
