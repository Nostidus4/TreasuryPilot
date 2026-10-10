# TreasuryPilot: Tech Stack

**Status:** Draft for gate G2 · **Date:** 2026-10-11 · Decisions Q23–Q36 in `decisions-log.md`; ADRs in `docs/adr/`.

## Selection drivers

1. **Team:** 2 main developers who prefer Python. 3 advisors who don't code.
2. **The security story is the product.** Enforcement lives on-chain. Off-chain components must make trust boundaries obvious: AI, validator, signer, contract.
3. **Requirements:** NFR-REL-02 requires zero double payments, which needs a transactional outbox. NFR-SEC-03 requires key isolation. F-160 requires one-command reproducibility.
4. **Few moving parts in M1.** Every extra service is a demo-day risk.

## Summary

| Layer | Choice | ADR |
|---|---|---|
| Smart contracts | Solidity 0.8.x, Foundry (forge/anvil/cast), Safe{Core} contracts (pinned), OpenZeppelin (pinned), Slither | ADR-002, ADR-003 |
| Smart account | Safe + custom `TreasuryPilotModule` (one instance per treasury) | ADR-002 |
| Backend API | Python 3.12, FastAPI, Pydantic v2, Uvicorn | ADR-010 |
| Domain core | `packages/py-core`: pure Python (financial engine, policy, domain types), no I/O | ADR-001 |
| Persistence | PostgreSQL 16, SQLAlchemy 2 (async), Alembic | ADR-004 |
| Jobs | Celery 5 + Redis 7 (broker) + Celery beat; Postgres transactional outbox + advisory locks | ADR-007 |
| Chain access | web3.py, eth-account (EIP-712), safe-eth-py; 2 RPC providers with failover | ADR-002 |
| Signer | Separate FastAPI service with an encrypted keystore (M1) and a KMS adapter (Prod) | ADR-006 |
| AI | Anthropic Python SDK (Claude), tool use + structured outputs, in-house orchestrator, model routing per task | ADR-005 |
| Auth | In-house: email magic link (Resend) + SIWE (`siwe` lib), httpOnly cookie sessions, DB RBAC | ADR-009 |
| Frontend | React 18 + Vite + TypeScript, wagmi/viem + RainbowKit, TanStack Query, React Hook Form + Zod, Tailwind + shadcn/ui, Recharts, OpenAPI-generated client | ADR-013 |
| Realtime UI | Server-Sent Events from the API | ADR-010 |
| Notifications | In-app (DB) + Telegram Bot API; email (Resend) Later | — |
| Storage | S3-compatible object storage (MinIO locally, any S3 in cloud), private bucket + signed URLs | ADR-008 |
| Observability | structlog (JSON), OpenTelemetry SDK, Sentry, Prometheus `/metrics` | ADR-011 |
| Testing | pytest + hypothesis (property tests), Foundry fuzz/invariant, Playwright (E2E), custom AI eval harness | — |
| Tooling | uv (Python), pnpm (web), ruff + mypy, eslint + prettier, pre-commit, gitleaks | ADR-001 |
| CI/CD | GitHub Actions; container images to GHCR | ADR-008 |
| Runtime M1 | Docker Compose on one cloud VM (+ same compose locally) | ADR-008 |

---

## Details: why, alternatives, trade-offs

### Smart contracts: Solidity + Foundry + Safe
- **Why:** Safe is the de-facto smart account; its module system lets an approved module act without per-transaction owner signatures, which is exactly delegated authority. Foundry gives fast fuzz and invariant testing (S1) and Anvil for reproducible local chains.
- **Alternatives:** Hardhat (slower tests, weaker fuzzing); Zodiac Roles only (cannot verify EIP-712 approvals, fingerprints, buffers or treasury-wide counters); ERC-4337/7579 accounts (bundler and paymaster overhead).
- **Trade-offs:** The custom module is security-critical code that has not been audited. Mitigations: small surface, no generic execute, invariant tests, static analysis.

### Backend: Python + FastAPI
- **Why:** The team's language. Pydantic gives strict schemas for both API and LLM structured outputs. OpenAPI is generated automatically, from which the web client is generated.
- **Alternatives:** Django + DRF (heavier, ORM coupled); Node/TS (matches the web3 ecosystem better, but not the team's strength).
- **Trade-offs:** Python web3 tooling is less ergonomic than viem. This is acceptable because heavy signing UX lives in the browser (wagmi).

### Domain core as a pure package
- **Why:** The financial engine and policy are the most important logic. Keeping them free of I/O makes them easy to property-test, and lets the API, worker and benchmark share them.
- **Trade-off:** Discipline is required to keep I/O out (enforced by an import-linter rule).

### PostgreSQL + SQLAlchemy + Alembic
- **Why:** Relational integrity for money, states and audit. Transactional outbox. Advisory locks for per-treasury serialization. JSONB for evidence.
- **Alternatives:** MongoDB (weak transactional guarantees for this use), SQLite (no concurrency for workers).
- **Trade-offs:** Migrations need care. Alembic is part of CI.

### Celery + Redis (Q32)
- **Why (lead's decision):** A familiar Python job system with retries, scheduling (beat) and monitoring (Flower).
- **How we keep it safe:** Celery is a *dispatcher*, not the source of truth. Every money-moving operation is first written to the Postgres `operations` table (outbox) in the same transaction as the state change. Celery tasks are idempotent and reload state from Postgres. Per-treasury sequencing uses `pg_advisory_xact_lock(treasury_id)`. Celery uses `acks_late=True` and `task_reject_on_worker_lost=True`.
- **Alternatives:** A Postgres-only queue (fewer components; this was the BA recommendation), Dramatiq/RQ.
- **Trade-offs:** One more service (Redis). Possible duplicate delivery, which is handled by idempotency.

### Signer service
- **Why:** BR-092 / NFR-SEC-03. It is the only process holding the executor key. It accepts only payloads that carry a valid validator attestation.
- **Alternatives:** Signing inside the worker (the key would sit next to LLM-calling code); MPC/TEE providers (a third-party dependency in the scored security component).
- **Trade-offs:** An extra service. M1 keystore security is lower than KMS (documented risk).

### AI: Claude via SDK, no agent framework
- **Why:** Few tools, strict schemas and a deterministic validator. A framework would hide the boundary we want judges to see. Claude handles PDF input natively (no OCR service). Model routing: a smaller model for extraction, a stronger model for planning, explanations and the Copilot.
- **Alternatives:** LangChain/LangGraph (abstraction overhead, harder to audit), other LLM providers (possible later through the adapter).
- **Trade-offs:** We write our own small orchestrator, tool-loop and eval harness.

### Auth: in-house magic link + SIWE
- **Why:** Small scope, full control over RBAC and maker-checker. SIWE wallet linking has to be built anyway.
- **Alternatives:** Clerk/Auth0/Supabase (vendor lock-in, awkward custom RBAC), fastapi-users.
- **Trade-offs:** We own session security. ASVS L1 checklist, rate limiting and tests apply.

### Frontend: React + Vite + wagmi
- **Why:** wallet connection and EIP-712/SIWE signing in the browser require JavaScript. The SPA talks to a separate API. shadcn/ui speeds up good-looking tables and forms.
- **Alternatives:** Next.js (SSR not needed), Streamlit (no wallet signing UX).
- **Trade-offs:** A second language in the repo. The generated client avoids type drift.

### Runtime: Docker Compose on one VM
- **Why:** One artifact for local, CI and demo; judges can open the URL or run it themselves.
- **Alternatives:** Split PaaS (more accounts and configuration), Kubernetes (overkill).
- **Trade-offs:** Single point of failure for the demo. Mitigation: a recorded video and a local fallback.

### Testing
| Level | Tool | Scope |
|---|---|---|
| Unit | pytest, hypothesis | py-core engine/policy, API handlers |
| Contract | forge test (unit, fuzz, invariant), Slither | TreasuryPilotModule |
| Integration | pytest + Anvil + docker compose | API ↔ worker ↔ signer ↔ chain |
| E2E | Playwright (with a mocked wallet for CI) | approval, plan timeline, reconciliation |
| AI eval | custom harness (F-092) | extraction accuracy, B1 vs B2, red-team |
| Reliability | scenario runner (F-164) | 30× local, 10× testnet |
