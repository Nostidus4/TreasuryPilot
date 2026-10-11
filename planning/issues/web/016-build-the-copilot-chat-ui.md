# [WEB] Build the Copilot chat UI

| Field | Value |
|---|---|
| **ID** | WEB-016 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Review |
| **Traces to** | FR-801 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-090: Treasury Copilot (what-if)

Problem behind this work (from `docs/FEATURES.md`):

- **F-090** solves: Fast, explainable decision support. Interaction quality.

## Objective

Ask treasury questions in the app.

## Scope

- Chat panel with streaming
- citations rendered as expandable tool results
- clear 'AI explanation' labelling
- suggested questions

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- AGT-012: Build the Copilot backend

## Acceptance criteria

- [ ] An answer shows citations that open the underlying numbers

## Testing requirements

- E2E with recorded responses

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
