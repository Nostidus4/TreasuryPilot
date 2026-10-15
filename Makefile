SHELL := /bin/sh
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
COREPACK_HOME ?= $(CURDIR)/.cache/corepack
PNPM := corepack pnpm@9.15.9
ENV_FILE ?= infra/env/.env
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/compose.yaml
FOUNDRY_IMAGE := ghcr.io/foundry-rs/foundry:v1.8.5
FOUNDRY := docker run --rm --entrypoint forge -v "$(CURDIR):/workspace" -w /workspace/contracts $(FOUNDRY_IMAGE)
SLITHER_VERSION := $(shell cat contracts/.slither-version)
SLITHER_IMAGE := treasurypilot-slither:$(SLITHER_VERSION)

export UV_CACHE_DIR
export COREPACK_HOME

.DEFAULT_GOAL := help

.PHONY: help bootstrap check-env dev infra down logs ps smoke openapi config-check web-dev \
	test test-python test-web test-contracts lint lint-python lint-web lint-contracts slither format deploy-local seed scenario reliability verify-sepolia

help:
	@echo "TreasuryPilot developer commands"
	@echo "  make bootstrap       Install locked Python and Node dependencies"
	@echo "  make dev             Build and start the complete local Compose stack"
	@echo "  make infra           Start PostgreSQL, Redis, MinIO and Anvil only"
	@echo "  make down            Stop the local stack"
	@echo "  make smoke           Check every exposed local service"
	@echo "  make openapi         Regenerate the typed web API client"
	@echo "  make config-check    Verify Sepolia config against live chain state"
	@echo "  make web-dev         Start the Vite development server"
	@echo "  make test            Run Python, web and contract tests"
	@echo "  make deploy-local    Deploy demo Safes and TreasuryPilot to a fresh Anvil chain"
	@echo "  make seed            Deploy to Anvil and seed the idempotent TEST demo dataset (after make dev)"
	@echo "  make reliability    Run demo-main 30x on Anvil (LOCAL_RUNS); TESTNET_RUNS=N on Sepolia reads 0% until the runner can drive Sepolia"
	@echo "  make scenario       List scenarios, or run one with NAME=<scenario>"
	@echo "  make verify-sepolia  Verify the published Sepolia implementation, factory and tUSDC on Etherscan"
	@echo "  make lint            Run all configured quality gates"
	@echo "  make slither         Run Slither on contracts (report in contracts/slither-report/)"
	@echo "  make eval-validate   Validate synthetic evaluation fixtures and reference labels"
	@echo "  make eval-redteam    Run the red-team invoices through extraction (recorded model)"

.PHONY: eval-validate
eval-validate:
	uv run --frozen python evals/validate.py

.PHONY: eval-redteam
eval-redteam:
	uv run --frozen python -m treasurypilot_worker.redteam --out docs/evidence/redteam-results.md

bootstrap:
	uv sync
	CI=1 $(PNPM) install --frozen-lockfile

check-env:
	@test -f "$(ENV_FILE)" || { echo "Missing $(ENV_FILE). Copy infra/env/.env.example and fill required values."; exit 1; }

dev: check-env
	$(COMPOSE) --profile local up --build -d

infra: check-env
	$(COMPOSE) --profile local up -d postgres redis minio minio-init anvil

down: check-env
	$(COMPOSE) --profile local down --remove-orphans

logs: check-env
	$(COMPOSE) --profile local logs -f --tail=200

ps: check-env
	$(COMPOSE) --profile local ps

smoke:
	uv run python infra/scripts/smoke.py

openapi:
	uv run python -m treasurypilot_api.export_openapi --output apps/web/openapi.json
	$(PNPM) --dir apps/web generate:api
	$(PNPM) exec prettier --write apps/web/openapi.json apps/web/src/lib/api/schema.d.ts

config-check:
	uv run python infra/scripts/config_check.py

web-dev:
	$(PNPM) --dir apps/web dev

test: test-python test-web test-contracts

test-python:
	uv run pytest

test-web:
	$(PNPM) --dir apps/web test

test-contracts:
	$(FOUNDRY) test

deploy-local:
	infra/scripts/deploy-local.sh

# Skips the (Foundry-only) deploy while the manifest's module still has code on Anvil.
seed: check-env
	uv run python infra/scripts/seed_local.py --check-deployed || $(MAKE) deploy-local
	set -a; . ./$(ENV_FILE); set +a; uv run python infra/scripts/seed_local.py
	grep -q '^TP_PLATFORM_CHAIN_CONFIG_PATH=' $(ENV_FILE) || printf '\nTP_PLATFORM_CHAIN_CONFIG_PATH=/app/deployments/local/chains.json\nTP_DEPLOYMENTS_DIR=/app/deployments/local\n' >> $(ENV_FILE)
	$(COMPOSE) up --detach --no-deps --force-recreate --wait api

# make scenario NAME=pause (or `make scenario` to list)
scenario:
	uv run python infra/scripts/scenario.py $(if $(NAME),run $(NAME),list)

# make reliability [LOCAL_RUNS=30] [TESTNET_RUNS=0]; needs Anvil + `make deploy-local`;
# TESTNET_RUNS>0 also needs TP_SEPOLIA_RPC_URL. Writes docs/evidence/reliability-<date>.md
# (a same-day rerun overwrites the report).
reliability:
	uv run python infra/scripts/reliability.py --local-runs $(or $(LOCAL_RUNS),30) --testnet-runs $(or $(TESTNET_RUNS),0)

verify-sepolia:
	uv run python infra/scripts/verify_sepolia_contracts.py

lint: lint-python lint-web lint-contracts

lint-python:
	uv run ruff check packages services infra/scripts infra/minio-init
	uv run ruff format --check packages services infra/scripts infra/minio-init
	uv run mypy packages/py-core/src services/api/src services/worker/src services/signer/src infra/scripts
	uv run lint-imports

lint-web:
	$(PNPM) --dir apps/web lint
	$(PNPM) --dir apps/web typecheck
	$(PNPM) --dir apps/web build
	$(PNPM) run format:check

lint-contracts:
	$(FOUNDRY) fmt --check
	$(FOUNDRY) build

slither:
	docker build -q --build-arg FOUNDRY_IMAGE=$(FOUNDRY_IMAGE) --build-arg SLITHER_VERSION=$(SLITHER_VERSION) \
		-t $(SLITHER_IMAGE) -f contracts/docker/slither.Dockerfile contracts/docker >/dev/null
	rm -rf contracts/slither-report && mkdir -p contracts/slither-report
	docker run --rm -v "$(CURDIR):/workspace" -w /workspace/contracts $(SLITHER_IMAGE) . \
		--config-file slither.config.json \
		--json slither-report/slither.json \
		--sarif slither-report/slither.sarif \
		--checklist > contracts/slither-report/slither.md
	@echo "Slither report: contracts/slither-report/"

format:
	uv run ruff check --fix packages services infra/scripts infra/minio-init
	uv run ruff format packages services infra/scripts infra/minio-init
	$(PNPM) run format
	$(FOUNDRY) fmt
