# Architecture Decision Records

Format: Context → Decision → Alternatives → Consequences. Status values are `Proposed`, `Accepted` and `Superseded`.
Accepted at gate G2 unless marked otherwise.

| ADR | Title | Status |
|---|---|---|
| 001 | Monorepo, languages and module boundaries | Proposed |
| 002 | Safe + custom TreasuryPilotModule (one per treasury) | Proposed |
| 003 | EIP-712 for approvals, exceptions and plan attestations | Proposed |
| 004 | PostgreSQL as system of record + transactional outbox | Proposed |
| 005 | Claude via SDK; AI is advisory, never authoritative | Proposed |
| 006 | Signer service and executor key management | Proposed |
| 007 | Celery + Redis for job execution, Postgres for truth | Proposed |
| 008 | Docker Compose runtime for M1 | Proposed |
| 009 | Authentication: magic link + SIWE, cookie sessions, RBAC | Proposed |
| 010 | FastAPI REST + OpenAPI-generated TS client + SSE | Proposed |
| 011 | Observability stack | Proposed |
| 012 | M1 chain and stablecoin | **Open (owner: Phúc)** |
| 013 | Frontend: React + Vite + wagmi | Proposed |
| 014 | Money as integer base units end-to-end | Proposed |
