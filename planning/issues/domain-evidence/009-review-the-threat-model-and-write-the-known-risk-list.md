# [DOMAIN] Review the threat model and write the known-risk list

| Field | Value |
|---|---|
| **ID** | DOM-009 |
| **Epic** | M20 · Domain & Evidence (non-code) |
| **Module** | `domain-evidence` ([spec](../../../docs/modules/domain-evidence/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | M (~1 day) |
| **Area** | non-code |
| **Status** | Ready for Assignment |
| **Traces to** | SYSTEM_ARCHITECTURE §3, NFR-SEC |
| **Blocks** | DOM-011 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Domain & Evidence (non-code)**. It supports:

- (supporting work; no single feature)

This is enabling work: other tickets cannot start, or evidence cannot be produced, without it.

## Objective

An honest list of what can still go wrong.

## Scope

- Review trust boundaries and contract design
- list residual risks (unaudited contract, RPC trust, signer host, owner actions outside the mandate, LLM errors)
- severity and mitigation per risk

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- None

## Acceptance criteria

- [ ] docs/security/known-risks.md with at least 10 risks, each with a mitigation or acceptance

## Testing requirements

- Not applicable (non-code). Review by a second person is required.

## Definition of Done

- [ ] Deliverable committed to the repository at the stated path
- [ ] Reviewed by one other team member
- [ ] Linked from the relevant document or issue
