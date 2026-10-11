# [DOMAIN] Write the security self-assessment report

| Field | Value |
|---|---|
| **ID** | DOM-011 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | Submission item 05 |
| **Blocks** | DOM-012 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- (supporting work; no single feature)

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

The required submission document on permission tiers and known risks.

## Scope

- English report: permission-tier table (Owner, Approver, Guardian, Executor, AI) with what each can and cannot do and where it is enforced
- known-risk list
- test evidence summary

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- DOM-009: Review the threat model and write the known-risk list
- SC-015: Run static analysis and write the findings report

## Acceptance criteria

- [ ] Report in docs/submission/security-self-assessment.md reviewed by a developer

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
