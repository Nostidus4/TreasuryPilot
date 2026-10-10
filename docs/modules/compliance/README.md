# M14 · Compliance

**Status:** Draft for gate G2 · **Path:** `docs/modules/compliance/`

## Purpose
Screening adapter (fixture in M1), data classification/minimization, KYB/Travel Rule/retention (Later).

## Features
F-110, F-111 (Later), F-112 (Later), F-113, F-114 (Later)

## Inputs
Addresses, data classification rules.

## Outputs
Screening results; redaction utilities; encryption helpers.

## APIs
Internal adapter: `screen(address) -> ScreeningResult`.

## Data model
screenings

## Dependencies
Provider (fixture in M1).

## Security concerns
Fail-closed screening; the fixture is labelled TEST; PII never goes on-chain.

## Failure scenarios
Provider error → registration blocked; PAY uses a cached result within its TTL, otherwise blocks.

## Open questions
Production provider choice (Later).
