# M15 · Audit & Evidence

**Status:** Draft for gate G2 · **Path:** `docs/modules/audit/`

## Purpose
Hash-chained audit log, evidence bundles, coverage/uncertainty labels.

## Features
F-120, F-121, F-122

## Inputs
Every action/event from all modules.

## Outputs
Audit records, verification results, evidence JSON.

## APIs
`/audit-log`, `/audit-log/verify`, `/requests/{id}/evidence` (API_SPEC §6).

## Data model
audit_log, evidence_bundles

## Dependencies
All modules write; no business dependency.

## Security concerns
Tamper evidence (hash chain + no-update trigger); audit write failure → fail closed for financial actions.

## Failure scenarios
Storage full → alert; financial actions blocked (fail closed).

## Open questions
Daily on-chain anchoring of the hash root (Later).
