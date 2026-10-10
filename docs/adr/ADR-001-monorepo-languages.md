# ADR-001: Monorepo, languages and module boundaries
**Status:** Accepted (G2, 2026-10-11) · **Date:** 2026-10-11 · **Decisions:** Q23, Q30, Q34

## Context
The team has 2 developers who prefer Python. The browser needs JS for wallet signing. The contracts are Solidity. The financial core must be testable in isolation and shared by the API, the worker and the benchmark.

## Decision
One repository:
- `apps/web` (TypeScript)
- `services/api`, `services/worker`, `services/signer` (Python, uv workspace)
- `packages/py-core` (pure Python domain, financial engine, policy; no I/O)
- `contracts/` (Foundry)
- `infra/`, `docs/`, `planning/`

Module boundaries are enforced with `import-linter` contracts: py-core imports nothing from services; modules talk through service interfaces, never through each other's tables.

## Alternatives
- Multi-repo: version skew and harder for 2 developers.
- All TypeScript: does not match team skills.
- All Python including the UI (Streamlit): no proper wallet signing.

## Consequences
- One PR can change a contract, the API and the UI together.
- CI must run three toolchains (uv, pnpm, forge).
