# Architecture Decision Records

Format: Context → Decision → Alternatives → Consequences. Status values are `Proposed`, `Accepted` and `Superseded`.
Accepted at gate G2 unless marked otherwise.

| ADR | Title | Status |
|---|---|---|
| 001 | Monorepo, languages and module boundaries | Accepted (G2, 2026-10-11) |
| 002 | Safe + custom TreasuryPilotModule (one per treasury) | Accepted (G2, 2026-10-11) |
| 003 | EIP-712 for approvals, exceptions and plan attestations | Accepted (G2, 2026-10-11) |
| 004 | PostgreSQL as system of record + transactional outbox | Accepted (G2, 2026-10-11) |
| 005 | Claude via SDK; AI is advisory, never authoritative | Accepted (G2, 2026-10-11) |
| 006 | Signer service and executor key management | Accepted (G2, 2026-10-11) |
| 007 | Celery + Redis for job execution, Postgres for truth | Accepted (G2, 2026-10-11) |
| 008 | Docker Compose runtime for M1 | Accepted (G2, 2026-10-11) |
| 009 | Authentication: magic link + SIWE, cookie sessions, RBAC | Accepted (G2, 2026-10-11) |
| 010 | FastAPI REST + OpenAPI-generated TS client + SSE | Accepted (G2, 2026-10-11) |
| 011 | Observability stack | Accepted (G2, 2026-10-11) |
| 012 | M1 chain and stablecoin | **Open (owner: Phúc)** |
| 013 | Frontend: React + Vite + wagmi | Accepted (G2, 2026-10-11) |
| 014 | Money as integer base units end-to-end | Accepted (G2, 2026-10-11) |
