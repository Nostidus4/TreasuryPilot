# [EXECUTION] Load the executor key from an encrypted keystore

| Field | Value |
|---|---|
| **ID** | EXE-006 |
| **Epic** | M10 · Orchestration & Execution |
| **Module** | `execution` ([spec](../../../docs/modules/execution/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Review |
| **Traces to** | NFR-SEC-03 |
| **Blocks** | — |

## Context

This ticket belongs to the epic **Orchestration & Execution**. It supports:

- F-061: Sequential executor & signer service

Problem behind this work (from `docs/FEATURES.md`):

- **F-061** solves: Key isolation from the LLM and the API process. Ordering safety.

## Objective

The executor key is never in plain text in the repo, image or environment listing.

## Scope

- Encrypted JSON keystore mounted read-only
- password from a Docker secret
- health endpoint returns the executor address and gas balance only

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- EXE-005: Build the signer service

## Acceptance criteria

- [ ] The service refuses to start without the keystore or with a wrong password
- [ ] The private key never appears in logs or the health response

## Testing requirements

- Security: log scan test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
