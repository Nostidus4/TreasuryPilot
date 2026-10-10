# M05 · Invoices & Payment Requests

**Status:** Draft for gate G2 · **Path:** `docs/modules/invoices/`

## Purpose
Intake (manual, CSV, upload → M09 extraction), request revisions, fingerprints, flags, approval typed-data and signature verification, and the request state machine.

## Features
F-030, F-031 (non-AI part), F-032, F-033 (Later), F-034 (Later), F-037, F-038, F-039, F-040 (Later), F-041 (Later)

## Inputs
Request inputs, files, CSV, Approver signatures, extraction results from M09.

## Outputs
Requests in states, approvals, flags, fingerprints. Approved requests are consumed by M07/M10.

## APIs
`/requests…`, `/upload`, `/import-csv`, `/terms/confirm`, `/submit`, `/approval-typed-data`, `/approve`, `/reject`, `/cancel` (API_SPEC §4).

## Data model
payment_requests, request_revisions, documents, extractions, flags, approvals, request_status_events

## Dependencies
M01 (maker-checker), M03 (payees), M09 (extraction, anomaly), M14 (screening), S3 storage, M15.

## Security concerns
Tampering after approval (revision bump invalidates approvals); duplicate invoices (fingerprint, DB + contract); CSV formula injection; malicious files (type/size limits, no server-side rendering); untrusted text (BR-070).

## Failure scenarios
Extraction timeout → manual path. Concurrent edits → 412 via ETag.

## Open questions
None open after G1.
