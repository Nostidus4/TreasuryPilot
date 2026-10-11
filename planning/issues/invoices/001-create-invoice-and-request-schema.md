# [INVOICES] Create invoice and request schema

| Field | Value |
|---|---|
| **ID** | INV-001 |
| **Epic** | M05 · Invoices & Payment Requests |
| **Module** | `invoices` ([spec](../../../docs/modules/invoices/README.md)) |
| **Phase / Priority** | M1 / P0 |
| **Size** | S (≤ 0.5 day) |
| **Area** | backend |
| **Status** | Ready for Assignment |
| **Traces to** | DATA_MODEL §2.4 |
| **Blocks** | INV-002, EXE-001 |
| **Submission cut** | A |

## Context

This ticket belongs to the epic **Invoices & Payment Requests**. It supports:

- F-030: Manual invoice entry
- F-031: PDF/image invoice upload & AI extraction
- F-032: CSV bulk import
- F-033: Email-forwarding inbox
- F-034: Inbound API / webhook intake
- F-035: Payment-terms extraction
- F-036: Anomaly & fraud-signal detection
- F-037: Duplicate-invoice fingerprint
- F-038: Invoice approval via EIP-712 signature
- F-039: Payment request lifecycle & state machine

Problem behind this work (from `docs/FEATURES.md`):

- **F-030** solves: The baseline intake channel.
- **F-031** solves: Manual data entry and missed terms.
- **F-032** solves: Batch payouts (e.g., 40+ contractors).

## Objective

Tables for requests, revisions, documents, extractions, flags, approvals and status events.

## Scope

- Alembic migration and models per docs/modules/invoices §4 (payment_requests with issue_date, invoice_hash, onchain_request_id, source, cancel_onchain
- request_revisions
- documents
- flags with revision and status
- approvals with acknowledged_flag_ids and solo_mode
- csv_imports
- request_status_events)
- partial unique index (treasury_id, fingerprint) excluding Rejected/Cancelled/Expired
- optimistic-lock version column
- append-only triggers on approvals (except status) and status events

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- MDT-001: Create mandate, payee and exception schema

## Acceptance criteria

- [ ] Migration applies and downgrades
- [ ] The duplicate-fingerprint index rejects a second active request but allows one after the first is Cancelled
- [ ] UPDATE of approval fields other than status is refused by the DB

## Testing requirements

- Integration: migration test

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
