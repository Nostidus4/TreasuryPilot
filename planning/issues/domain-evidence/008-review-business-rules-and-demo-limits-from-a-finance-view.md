# [DOMAIN] Review business rules and demo limits from a finance view

| Field | Value |
|---|---|
| **ID** | DOM-008 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Review |
| **Traces to** | BUSINESS_RULES.md, OQ-05 |
| **Blocks** | DOM-013 |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- (supporting work; no single feature)

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

Make sure the rules and demo numbers make sense to a finance professional.

## Scope

- Read BUSINESS_RULES.md
- comment on realism of limits, buffer, cooling period, maker-checker
- propose the demo company profile and numbers

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- None

## Acceptance criteria

- [ ] Written review in docs/reviews/finance-review.md
- [ ] Demo numbers agreed and recorded

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
