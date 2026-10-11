# [DOMAIN] Author the red-team invoice set (20)

| Field | Value |
|---|---|
| **ID** | DOM-006 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | non-code |
| **Status** | Ready for Assignment |
| **Traces to** | AGT-015 |
| **Blocks** | AGT-015 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- F-091: Untrusted-data boundary & prompt-injection defense
- F-163: Security test suites

Problem behind this work (from `docs/FEATURES.md`):

- **F-091** solves: Injected instructions changing payees or limits.
- **F-163** solves: Evidence for the Security criterion.

## Objective

Attack invoices to test the defenses.

## Scope

- 20 invoices in evals/redteam: address swap, 'pre-approved' text, limit-raise request, hidden text, homoglyph address, duplicate with new number
- expected safe outcome per case

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- None

## Acceptance criteria

- [ ] 20 cases each with a description and expected outcome

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
