# [DOMAIN] Document execution evidence requirements and the Sepolia assumption

| Field | Value |
|---|---|
| **ID** | DOM-003 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | non-code |
| **Status** | Ready for Assignment |
| **Traces to** | OQ-01, Submission item 06, NFR-CMP-01, ADR-012, ADR-019 |
| **Blocks** | — |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- (supporting work; no single feature)

This documentation ticket records the published execution-evidence wording and the team's network interpretation. Optional organizer clarification does not block implementation or submission.

## Objective

Record the published on-chain execution-evidence requirement and distinguish it from the team's network choice.

## Scope

- Cite PBCSF Appendix 2, page 3, submission checklist item 06 in OPEN_QUESTIONS.md
- Record that on-chain submissions require real on-chain transaction hashes, while the checklist does not specify testnet or mainnet
- Record Ethereum Sepolia as the team's working choice under ADR-012/019 and NFR-CMP-01, not as explicit organizer confirmation
- Keep organizer clarification optional and non-blocking, and record an actual reply only if one is obtained

## Out of scope

Sending an organizer email, public deployment and collecting transaction hashes are not required to complete this documentation ticket. Actual deployment/evidence stays with DOM-001/002 and the relevant execution tickets.

## Technical notes

Checked 2026-10-14 against the published PBCSF rules. PH-3 records the team's interpretation, not an organizer reply. No mandatory email or 14/10 reply deadline; no automatic switch to mainnet. Source: [PBCSF Appendix 2, page 3](https://www.its.ac.id/international/wp-content/uploads/sites/66/2026/10/PBCSF-Appendix-2-Problem-Description-and-Competition-Rules-for-International-Track.pdf).

## Dependencies

- None

## Acceptance criteria

- [ ] OPEN_QUESTIONS.md cites the source, page and checklist item with the exact transaction-hash requirement
- [ ] The official requirement and the team's Sepolia assumption are explicitly distinguished
- [ ] No mandatory organizer email or reply blocks development or submission in this ticket
- [ ] Any future network restriction is handled through a reviewed decision instead of an undocumented mainnet switch

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
