# M01 · Identity & Access

**Status:** Draft for gate G2 · **Path:** `docs/modules/identity/`

## Purpose
Authenticate humans, link wallets (SIWE), manage organizations, memberships, the 8 roles, RBAC checks and maker-checker.

## Features
F-001, F-002, F-003, F-004, F-005, F-006 (Later), F-007 (Later)

## Inputs
Email, magic-link tokens, SIWE messages and signatures, invites, role changes.

## Outputs
Sessions, user/org/membership records, linked wallets, permission decisions for other modules.

## APIs
`/auth/*`, `/me`, `/me/wallets`, `/orgs`, `/orgs/{o}/members`, `/orgs/{o}/invites` (API_SPEC §1). Internal: `require_role(org, roles)`, `assert_maker_checker(request, user)`.

## Data model
users, sessions, magic_links, wallet_links, siwe_nonces, organizations, memberships, invites

## Dependencies
M15 audit (writes), M13 notifications (invite email, Later). No upstream business dependency, so it is foundational.

## Security concerns
Session fixation and CSRF (double-submit token); brute force (rate limit); SIWE replay (single-use nonce, domain/chain checks); privilege escalation (role changes need OrgAdmin; last-admin guard); tenant isolation (org filter everywhere).

## Failure scenarios
Email provider down → no account half-created, retry message. Nonce store unavailable → reject linking. Clock skew → SIWE expiry tolerance ±2 min.

## Open questions
OQ-07 solo mode (resolved: allowed with flag).
