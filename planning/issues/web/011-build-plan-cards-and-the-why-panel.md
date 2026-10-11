# [WEB] Build plan cards and the Why panel

| Field | Value |
|---|---|
| **ID** | WEB-011 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | FR-917, BR-057 |
| **Blocks** | WEB-012, WEB-013 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-132: Plan cards & live execution timeline

Problem behind this work (from `docs/FEATURES.md`):

- **F-132** solves: Explainability and real-time feedback.

## Objective

Explain each plan: what, in which order, and why.

## Scope

- Plan card with steps, amounts, expected savings and planner source badge
- Why panel with validator reason codes (authoritative) and AI explanation (labelled)
- binding constraints

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-010: Build the treasury dashboard
- EXE-004: Implement the planning pipeline task

## Acceptance criteria

- [ ] Validator reasons and AI text are visually separate and labelled
- [ ] A RULE_BASED plan shows its badge

## Testing requirements

- E2E

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
