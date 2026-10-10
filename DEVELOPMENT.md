# Development Guide

> Implementation has not started. This guide describes the **target** developer workflow. Each command becomes real when the ticket that creates it is done (see `planning/issues/devex/`).

## Prerequisites

| Tool | Version | Used for |
|---|---|---|
| Docker + Docker Compose | recent | whole stack |
| [uv](https://docs.astral.sh/uv/) | latest | Python 3.12 envs and workspace |
| Node.js + pnpm | Node 22 LTS, pnpm 9 | `apps/web` |
| Foundry (forge, anvil, cast) | pinned in `contracts/foundry.toml` | contracts |

## First run (target)

```bash
cp infra/env/.env.example infra/env/.env   # fill in LLM key etc.
make dev                                    # compose profile "local": postgres, redis, minio, anvil, api, worker, worker-ai, beat, signer, web
make seed                                   # deploy contracts to Anvil, create org/treasury/payees/invoices
open http://localhost:5173
```

## Everyday commands (target)

| Command | What it does |
|---|---|
| `uv sync` | Install Python workspace dependencies |
| `uv run pytest packages/py-core` | Core unit + property tests |
| `uv run pytest services/api services/worker` | Service tests |
| `cd contracts && forge test` | Contract unit/fuzz/invariant tests |
| `pnpm --dir apps/web dev` | Web dev server |
| `make openapi` | Regenerate the TS client from the API |
| `make scenario name=demo-main` | Run a named scenario and export evidence |
| `make bench` | AI benchmark B1 vs B2 |
| `make reliability` | 30 local runs of the main scenario |

## Environments

| Profile | Chain | Assets | Purpose |
|---|---|---|---|
| `local` | Anvil | TestUSDC (labelled) | development, CI |
| `testnet` | see ADR-012 (owner: Phúc) | testnet stablecoin | demo, evidence |

Mainnet is **not** supported in M1. The scenario tooling refuses non-allowlisted chain ids.

## Secrets

Never commit secrets. `infra/env/.env.example` lists the names only. The signer keystore and its password are mounted as Docker secrets. `gitleaks` runs in pre-commit and CI.

## Database migrations

Alembic lives in `services/api/migrations`. Use one migration per PR when the schema changes. Never edit a merged migration.

## Money

Amounts are integers in base units everywhere (ADR-014). Never use floats for money.
