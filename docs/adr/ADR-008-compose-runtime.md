# ADR-008: Docker Compose runtime for M1
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q29

## Decision
A single `infra/compose.yaml` with profiles `local` (adds Anvil + seed), `testnet` and `ci`. M1 demo runs on one cloud VM behind Caddy (automatic TLS). Images are built in GitHub Actions and pushed to GHCR. Only `web` and `api` are public.

## Consequences
- The demo VM is a single point of failure → mitigated by a recorded video and a local runbook.
- Production redesign is a separate ADR (Later).
