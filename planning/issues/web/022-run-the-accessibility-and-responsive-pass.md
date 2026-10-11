# [WEB] Run the accessibility and responsive pass

| Field | Value |
|---|---|
| **ID** | WEB-022 |
| **Epic** | M16 · Web Application |
| **Module** | `web` ([spec](../../../docs/modules/web/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | frontend |
| **Status** | Ready for Assignment |
| **Traces to** | NFR-UX-01–04 |
| **Blocks** | — |
| **Submission cut** | After submission |

## Context

This ticket belongs to the epic **Web Application**. It supports:

- F-130: Treasury dashboard
- F-131: Approval inbox with diff & flags
- F-132: Plan cards & live execution timeline
- F-133: Reconciliation view
- F-134: Mandate & payee management UI
- F-135: Exception & review console

Problem behind this work (from `docs/FEATURES.md`):

- **F-130** solves: One glance at treasury health.
- **F-131** solves: Fast, informed approvals (P3).
- **F-132** solves: Explainability and real-time feedback.

## Objective

Core flows are usable and precise.

## Scope

- axe checks on approve, exceptions and dashboard
- keyboard navigation
- 390 px layouts for approval and notifications
- status-wording checklist review

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- WEB-014: Build the reconciliation view and export

## Acceptance criteria

- [ ] No critical axe violations on the three core flows
- [ ] The wording checklist is signed off

## Testing requirements

- Accessibility test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
