# Development Guide

> The development foundation is initialized. Business capabilities are added through the matching tickets in `planning/issues/`.

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker + Docker Compose | recent | whole stack |
| [uv](https://docs.astral.sh/uv/) | 0.11.3 | Python 3.12.13 envs and workspace |
| Node.js + pnpm | Node 22 LTS, pnpm 9.15.9 | `apps/web` |
| Foundry (forge, anvil, cast) | v1.8.5 (Docker) | contracts and local chain |

## Workspace bootstrap

```bash
uv sync
pnpm install --frozen-lockfile
make test
make lint
```

These commands install the locked workspaces and run all active quality gates.

## First run

```bash
cp infra/env/.env.example infra/env/.env   # runnable local defaults; add optional provider keys when needed
make dev                                    # postgres, redis, minio, anvil, api, workers, beat, signer, web
make smoke                                  # verify the exposed web/API/infra endpoints
open http://localhost:5173
```

The checked-in foundation intentionally does not seed business data or expose signing operations. Those arrive through their feature and security tickets.

## Everyday commands

| Command | What it does |
|---|---|
| `uv sync` | Install Python workspace dependencies |
| `uv run pytest packages/py-core` | Core unit + property tests |
| `uv run pytest services/api services/worker` | Service tests |
| `make test-contracts` | Contract tests in the pinned Foundry image |
| `make slither` | Slither static analysis in the pinned Foundry image; report in `contracts/slither-report/` |
| `pnpm --dir apps/web dev` | Web dev server |
| `make openapi` | Regenerate the TS client from the API |
| `make ps` / `make logs` | Inspect the Compose stack |
| `make down` | Stop the local stack without deleting volumes |
| `make scenario name=demo-main` | Run a named scenario and export evidence |
| `make bench` | AI benchmark B1 vs B2 |
| `make reliability` | 30 local runs of the main scenario |

The scenario, benchmark and reliability commands are introduced by their later implementation tickets.

## Environments

| Profile | Chain | Assets | Purpose |
|---|---|---|---|
| `local` | Anvil | TestUSDC (labelled) | development, CI |
| `testnet` | see ADR-012 (owner: Phúc) | testnet stablecoin | demo, evidence |

Mainnet is **not** supported in M1. The scenario tooling refuses non-allowlisted chain ids.

## Secrets

Never commit secrets. `infra/env/.env.example` contains only disposable local defaults and empty provider placeholders. The foundation signer exposes health only and receives no key; its implementation ticket must mount the keystore and password as Docker secrets. `gitleaks` runs in pre-commit and CI.

## Database migrations

Alembic lives in `services/api/migrations`. Use one migration per PR when the schema changes. Never edit a merged migration.

`make dev` runs a one-shot `migrate` service (`alembic upgrade head`) before the API starts, because the API syncs platform chain configuration into the database at startup. Outside Compose, run `DATABASE_URL=... uv run alembic -c services/api/alembic.ini upgrade head`; Alembic refuses to run without a `DATABASE_URL`.

## Money

Amounts are integers in base units everywhere (ADR-014). Never use floats for money.
