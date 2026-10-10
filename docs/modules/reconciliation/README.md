# M11 · Verification & Reconciliation

**Status:** Draft for gate G2 · **Path:** `docs/modules/reconciliation/`

## Purpose
Post-condition verification, reconciliation records and classification, CSV/journal export, on-chain attestations (P2), ERP (Later).

## Features
F-071, F-072, F-073, F-074, F-075 (Later)

## Inputs
Confirmed transactions, plan expectations, invoice data.

## Outputs
Verification results, reconciliation states, export files, attestation UIDs.

## APIs
`/reconciliations…`, `/exports/reconciliation.csv` (API_SPEC §6).

## Data model
verifications, reconciliations, recon_lines, chain_attestations

## Dependencies
M06, M10, M05, M15.

## Security concerns
Export injection (neutralize formulas); totals integrity (tests against the chain).

## Failure scenarios
Discrepancy → review item + circuit-breaker signal.

## Open questions
OQ-12 account mapping (resolved: generic + per-org).
