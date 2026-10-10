# M03 · Mandate, Payees, Exceptions & Pause (off-chain)

**Status:** Draft for gate G2 · **Path:** `docs/modules/mandate/`

## Purpose
Author mandate drafts, build Owner-signable Safe transactions, track activation/versions, manage the payee registry (screening + cooling), one-time exceptions, and pause/resume.

## Features
F-020, F-021, F-022, F-025, F-026, F-027 (rules config), F-028 (Later), F-029 (Later)

## Inputs
MandateConfig, payee proposals, screening results, Owner signatures, on-chain events.

## Outputs
Draft/active mandate versions, payee states, exception records, backend pause flag, Safe tx payloads.

## APIs
`/mandates`, `/activation-tx`, `/activation`, `/payees…`, `/pause`, `/resume-tx`, `/requests/{id}/exception` (API_SPEC §3).

## Data model
mandate_versions, mandate_status_events, vendors, payees, screenings, exceptions

## Dependencies
M01, M02, M04 (ABI), M06 (confirmations/events), M14 (screening), M15, M13.

## Security concerns
Draft ≠ on-chain (always read back before Active); a non-Owner writing a mandate (RBAC + only Safe T can call governance); exception replay (on-chain nonce); stale backend pause state (pause flag is checked by the trigger and executor).

## Failure scenarios
Activation tx stuck → PendingActivation and the old version stays in force. Screening provider down → registration blocked.

## Open questions
None open after G1.
