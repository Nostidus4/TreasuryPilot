# M19 · Developer Experience & Quality

**Status:** Detailed — decisions finalized by the tech lead under the project lead's delegation (2026-10-11) · **Path:** `docs/modules/devex/` · **Epic:** `[EPIC] M19 · Developer Experience & Quality`
**ADRs:** ADR-001 (monorepo), ADR-008 (Compose + Caddy), ADR-010 (OpenAPI client) · **See also:** `DEVELOPMENT.md`, `docs/REPOSITORY_STRUCTURE.md` · **Decisions:** M19-D1 … M19-D12 (§14)

---

## 1. Purpose and boundaries

M19 makes the codebase **easy to start, hard to break, and able to prove itself**: monorepo skeleton, one-command local stack, seed data, CI gates, module boundary checks, scenario runner, reliability harness, demo runbook and the testnet VM.

| In scope (M1) | Out of scope |
|---|---|
| Monorepo (uv + pnpm), pre-commit | Production hardening, multi-VM |
| Compose stack local + testnet profiles, Caddy TLS | |
| Seed, scenario runner, reliability harness, demo runbook | |
| CI: Python, contracts (fuzz, Slither), web + OpenAPI drift, gitleaks, import-linter | |

## 2. Features, requirements and rules

F-160 (FR-927), F-161 (FR-928, NFR-MAINT-01/03), F-162 (FR-929, BR-095), F-163 (FR-930, NFR-SEC-02/06/07), F-164 (FR-931, NFR-REL-01), F-151 (FR-925).

## 3. Concepts

| Term | Definition |
|---|---|
| **Profiles** | `local` (Anvil 31337, MinIO, all services) and `testnet` (Sepolia, no Anvil, Caddy). |
| **Scenario** | YAML in `scenarios/` describing setup, actions and expected outcomes; runs on an allowlisted chain only. |
| **Evidence** | Reports and bundles written to `docs/evidence/` (reliability, bench, red-team, extraction). |

## 4. Repository layout

`apps/web`, `services/{api,worker,signer}`, `packages/py-core`, `contracts/`, `infra/{compose.yaml, Caddyfile, env/.env.example}`, `evals/`, `scenarios/`, `deployments/`, `docs/`, `planning/`. Python 3.12, uv workspace; pnpm for web; Foundry pinned.

## 5. Make targets

| Target | Does |
|---|---|
| `make dev` / `make down` | start/stop postgres 16, redis 7, minio, anvil + app services |
| `make seed` | deploy contracts + Safes on Anvil, org/users/roles, treasury, active mandate, payees (one cooling), 5 invoices; idempotent |
| `make test` / `make lint` | all Python/web/contract tests / linters |
| `make openapi` | export OpenAPI and regenerate the TS client |
| `make deploy-local` / `make deploy-sepolia` | contracts via CREATE2 (SC-016) |
| `scenario run <name>` | demo-main, over-cap-exception, injected-invoice, crash-recovery, pause, unexpected-outflow *(added)*, fee-spike *(added)* |
| `make reliability` | 30 runs demo-main on Anvil + N on Sepolia → `docs/evidence/reliability-<date>.md` |
| `make bench`, `make eval-extraction`, `make redteam`, `make eval-validate` | AI evals (M09, M20) |

## 6. CI workflows

| Workflow | Gates |
|---|---|
| `ci.yml` (Python) | ruff, ruff format, mypy (strict py-core), pytest + coverage (py-core ≥ 85 %), import-linter, gitleaks |
| `contracts.yml` | forge fmt, build, test (fuzz 1k on PR, 10k on main; invariant runs 192 on PR, 750 on main, depth 50), Slither report-only with `slither-report` artifact (JSON, SARIF, markdown; SC-015 raises it to fail on high) |
| `web.yml` | eslint, tsc, vite build, OpenAPI client drift |
| `e2e.yml` (main + nightly) | Playwright happy path on Anvil (WEB-023), RCV-007 crash test *(mặc định: nightly)* |
| `images.yml` | build + push to GHCR tagged with git SHA |

Import-linter contracts: py-core forbids sqlalchemy, httpx, web3, celery, fastapi (ortools and eth-account allowed, ADR-015/ENG-010); services must not import each other; worker-ai code path must not import signer/attestation modules.

## 7. Flows

New dev: clone → `uv sync && pnpm install` → `make dev && make seed` → app at `http://localhost:5173` with printed login links (≤ 15 min). Deploy: push main → images → VM `docker compose --profile testnet pull && up -d`.

## 8. Algorithms — n/a (tooling).

## 9. Configuration

`.env.example` lists names only; secrets via Docker secrets (executor/sentinel/policy/receipt keystores and passwords, field key, LLM key, Sentry DSN, Telegram token). Only web and api exposed through Caddy; signer, postgres, redis, minio internal.

## 10. Security

gitleaks pre-commit + CI; no secrets in images; Slither + fuzz + invariants on contracts; scenario runner refuses non-allowlisted chain ids (BR-095); test assets labelled.

## 11. Failure scenarios

Flaky testnet → retries reported, never hidden (reliability report categorizes failures); Anvil reset → `make seed` idempotent.

## 12. Test plan

The workflows themselves; a planted fake secret is blocked; an illegal import fails CI; fresh-clone timing check; teammate dry-run of the runbook.

## 13. Tickets

DEV-001 → DEV-002 → DEV-011 → DEV-003 → DEV-004 → DEV-005 → DEV-006 → DEV-007 → DEV-008 → DEV-009 → DEV-010.

## 14. Decisions

| ID | Decision |
|---|---|
| M19-D1 | Monorepo with uv + pnpm + Foundry, pinned versions. |
| M19-D2 | Compose profiles local/testnet; Caddy TLS on one VM. |
| M19-D3 | Seed is idempotent and uses the public API where possible. |
| M19-D4 | Scenarios as YAML; chain-id allowlist. |
| M19-D5 | Added scenarios: unexpected-outflow, fee-spike. |
| M19-D6 | py-core coverage ≥ 85 % gate. |
| M19-D7 | Import-linter allows ortools and eth-account in py-core. |
| M19-D8 | Fuzz 1k on PR, 10k on main. |
| M19-D9 | E2E and crash test nightly + on main. |
| M19-D10 | Images tagged with git SHA in GHCR. |
| M19-D11 | Only web and api reachable from the internet. |
| M19-D12 | Reliability: 30 local runs + N Sepolia runs, failures categorized. |

## 15. v0.3 changes (ADR-019)

- Scenarios **D1–D10** as YAML (`scenarios/d01-refill-pay.yaml` … `d10-guardian-pause.yaml`), each with "must show" assertions; the runbook maps scenes to them.
- **Config gate** in CI (`make config-check`): chain id, token decimals and Aave Pool/aToken mapping must equal `deployments/<chainId>.json`; addresses only from official deployment data.
- Sepolia fork job (pinned block) for Aave integration tests.
- **Tickets:** DEV-007, DEV-008, DEV-010 revised; DEV-012 config gate (new).
