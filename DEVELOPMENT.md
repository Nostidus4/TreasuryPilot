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

## Using Supabase Postgres

Supabase is used only as managed Postgres 16 (ADR-004); auth stays in-house (ADR-009), so there is no Supabase Auth or `supabase-js`.

1. In the Supabase dashboard (project `flbztxutuqtbxjoflxsi`), click **Connect** and pick **Session pooler** (port 5432, host `aws-0-<region>.pooler.supabase.com`, user `postgres.flbztxutuqtbxjoflxsi`). The direct connection also works. Do not use the transaction pooler (port 6543): it breaks asyncpg prepared statements.
2. Put the string in the gitignored `infra/env/.env` as `SUPABASE_DATABASE_URL`, using the `postgresql+asyncpg://` scheme and `?ssl=require` (see `infra/env/.env.example`). URL-encode special characters in the password.
3. Run migrations, then start the stack, with the override file (Docker Compose >= 2.24):

```sh
docker compose --env-file infra/env/.env -f infra/compose.yaml -f infra/compose.supabase.yaml run --rm migrate
docker compose --env-file infra/env/.env -f infra/compose.yaml -f infra/compose.supabase.yaml up
```

The override points `api`, `worker`, `beat` and `migrate` at Supabase and drops their dependency on the local `postgres` container, which is then only started under the `local-postgres` profile. `worker-ai` requires `AI_DATABASE_URL` in this mode (compose fails fast if it is unset); give it a dedicated least-privilege Supabase role, never the core credential. `migrate`, `worker` and `beat` are also attached to the `public` network, since `internal` has no outbound access to reach Supabase.

## Running against Ethereum Sepolia

```sh
docker compose --env-file infra/env/.env -f infra/compose.yaml -f infra/compose.sepolia.yaml up -d --build
```

Do not enable the `local` or `ci` profiles; anvil is not needed. `worker` and `signer` are attached to the `public` network for outbound RPC access (`internal` has none). Combine with `-f infra/compose.supabase.yaml` if wanted.

- `SEPOLIA_RPC_URL` feeds `CHAIN_RPC_URL` for worker/signer (Alchemy URL goes here). `SEPOLIA_WEB_RPC_URL` feeds the web build arg `VITE_RPC_URL` (public RPC or domain-restricted key only, since it ships in the JS bundle). Both default to `https://ethereum-sepolia-rpc.publicnode.com`. `VITE_CHAIN_ID` becomes `11155111`. Rebuild the web image after changing either. Never commit keyed URLs.
- Current limitation: only the web wallet uses Sepolia today. No backend code reads `CHAIN_RPC_URL` yet, and `deployments/chains.json` stays empty until the treasury module is deployed to Sepolia and the manifest format gap in `deployments/README.md` is reconciled (the API config requires >= 2 distinct RPC URLs and a deployed `TREASURY_MODULE_IMPLEMENTATION`).
- Gas: the deployer, policy/signer and operational wallets need Sepolia ETH from a faucet ([Google Cloud Web3 faucet](https://cloud.google.com/application/web3/faucet/ethereum/sepolia) or [pk910](https://sepolia-faucet.pk910.de)). Test USDC for Aave comes from the [Aave faucet](https://app.aave.com/faucet/). Check `infra/scripts/check-sepolia-deploy.sh` and `deployments/11155111.json` for supply-cap caveats.

## Deploying to a testnet VM

One cloud VM runs the stack against Sepolia behind Caddy (automatic TLS), using images that the `Publish images` workflow (`.github/workflows/images.yml`) pushes to GHCR on every merge to `main`, tagged `ghcr.io/<owner>/treasurypilot-{api,worker,signer,web}:<git-sha>`. The `web` image is built for Sepolia (`VITE_CHAIN_ID=11155111`, public RPC).

1. VM: Docker Engine with Compose >= 2.24, DNS `A` records for `APP_DOMAIN` and `files.<APP_DOMAIN>` (Caddy proxies only presigned `GET`/`HEAD` requests under the `MINIO_BUCKET` path to MinIO and answers 403 to everything else; `MINIO_ROOT_PASSWORD` must still be strong because it signs those URLs) pointing at it. Firewall: allow inbound 22 (ideally your IP only), 80 and 443; deny everything else. Compose publishes only Caddy on 80/443; `web`, `api`, MinIO and Redis bind `127.0.0.1` only, and the signer publishes nothing.
2. Clone the repo at the commit to deploy and create the gitignored `infra/env/.env` from `infra/env/.env.example`: set `APP_DOMAIN`, `GHCR_OWNER`, `SUPABASE_DATABASE_URL`, `AI_DATABASE_URL`, `SEPOLIA_RPC_URL`, replace every local default password and keystore path, and replace the TEST `TP_TRAVEL_RULE_THRESHOLDS` with your own (or `{}`). For private images run `docker login ghcr.io` first.
3. `infra/scripts/deploy-testnet.sh <full-git-sha>` validates the config, pulls the images, runs `migrate`, then starts the stack with `--profile testnet --no-build`. To roll back, run it again with an earlier SHA.

Caddy serves `/api/*` (prefix stripped) from `api` and everything else from `web`.

Known gaps: `deployments/chains.json` stays empty until #31 publishes the Sepolia manifest (Aave test USDC and Pool come from it).

## Money

Amounts are integers in base units everywhere (ADR-014). Never use floats for money.

## Seeding the demo dataset

With `make dev` running, `make seed` deploys the contracts and three Safes to Anvil (needs Foundry only when no live deployment exists; re-running reuses `deployments/31337.json` while its module still has code, and a fresh Anvil or redeploy updates the stored addresses in place). It then runs `infra/scripts/seed_local.py`, which inserts one TEST organization with four users, a Ready treasury, an active mandate, a guardian setup with sentinel, an accepted fee policy, three payees (one still cooling), five invoices and a COMPLETE Safe config snapshot per Safe, then prints addresses and login links. The guardian is an EOA stand-in (Anvil account 3), not a Guardian Safe, and rows are written with SQL, not the public API. Snapshots count as fresh for 12 minutes, so re-run `make seed` to restore COMPLETE coverage. The script writes `deployments/local/` (git-ignored, mounted read-only into the `api` container) and `make seed` persists `TP_PLATFORM_CHAIN_CONFIG_PATH`/`TP_DEPLOYMENTS_DIR` in `infra/env/.env`, then recreates `api` so chain 31337 stays enabled across restarts. For an API outside Compose, use the values the script prints.
