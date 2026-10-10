# M18 · Platform Admin & Billing

**Status:** Draft for gate G2 · **Path:** `docs/modules/admin/`

## Purpose
Platform configuration (M1 via seed/config), tenant admin and billing (Later).

## Features
F-150 (Later), F-151, F-152 (Later)

## Inputs
Config files, admin actions.

## Outputs
Validated configuration; tenant states.

## APIs
`/platform/*` (Later UI).

## Data model
platform_settings, billing_* (Later)

## Dependencies
M02.

## Security concerns
No fund-moving capability (BR-094); all admin actions audited.

## Failure scenarios
Invalid config → refuse to start.

## Open questions
Pricing model (Later).
