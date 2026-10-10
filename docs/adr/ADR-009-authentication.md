# ADR-009: Authentication: magic link + SIWE, cookie sessions, RBAC
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q33 · **Features:** F-001–F-005

## Decision
- Login by email magic link: a single-use 15-minute token, hashed in the DB, sent via Resend (printed to the console in `local`).
- Sessions use an opaque id in an httpOnly, Secure, SameSite=Lax cookie, stored server-side in Postgres. CSRF uses the double-submit token for mutating requests.
- Wallet linking uses SIWE (EIP-4361) with server nonces; ERC-1271 is supported.
- RBAC is a membership-roles table. Permission checks run in FastAPI dependencies. Maker-checker is checked in the approval service.
- Rate limiting applies per IP and per account on auth endpoints.

## Alternatives
Clerk, Auth0, Supabase Auth, fastapi-users.

## Consequences
We own session security (ASVS L1 checklist). MFA and SSO come later (F-006/007).
