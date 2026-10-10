# M16 · Web Application

**Status:** Draft for gate G2 · **Path:** `docs/modules/web/`

## Purpose
All UI: onboarding, dashboard, approval inbox, plan/timeline, reconciliation, mandate & payees, exception console, Copilot, notifications.

## Features
F-130, F-131, F-132, F-133, F-134, F-135 (+ UI for most features)

## Inputs
API (generated client), SSE, wallet (wagmi).

## Outputs
User actions; wallet signatures (SIWE, EIP-712, Safe txs).

## APIs
Consumes API_SPEC.

## Data model
None (client state only).

## Dependencies
M01–M15 APIs.

## Security concerns
Typed-data display = what is signed; no secrets in the browser; CSP; precise status wording (F-122).

## Failure scenarios
API down → error states; wallet rejection → no state change.

## Open questions
None.
