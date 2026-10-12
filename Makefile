SHELL := /bin/sh
UV_CACHE_DIR ?= $(CURDIR)/.cache/uv
COREPACK_HOME ?= $(CURDIR)/.cache/corepack
PNPM := corepack pnpm@9.15.9
ENV_FILE ?= infra/env/.env
COMPOSE := docker compose --env-file $(ENV_FILE) -f infra/compose.yaml
FOUNDRY_IMAGE := ghcr.io/foundry-rs/foundry:v1.8.5
FOUNDRY := docker run --rm --entrypoint forge -v "$(CURDIR):/workspace" -w /workspace/contracts $(FOUNDRY_IMAGE)

export UV_CACHE_DIR
export COREPACK_HOME

.DEFAULT_GOAL := help

.PHONY: help bootstrap check-env dev infra down logs ps smoke openapi web-dev \
	test test-python test-web test-contracts lint lint-python lint-web lint-contracts format deploy-local

help:
	@echo "TreasuryPilot developer commands"
	@echo "  make bootstrap       Install locked Python and Node dependencies"
	@echo "  make dev             Build and start the complete local Compose stack"
	@echo "  make infra           Start PostgreSQL, Redis, MinIO and Anvil only"
	@echo "  make down            Stop the local stack"
	@echo "  make smoke           Check every exposed local service"
	@echo "  make openapi         Regenerate the typed web API client"
	@echo "  make web-dev         Start the Vite development server"
	@echo "  make test            Run Python, web and contract tests"
	@echo "  make deploy-local    Deploy demo Safes and TreasuryPilot to a fresh Anvil chain"
	@echo "  make lint            Run all configured quality gates"

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

format:
	uv run ruff check --fix packages services infra/scripts infra/minio-init
	uv run ruff format packages services infra/scripts infra/minio-init
	$(PNPM) run format
	$(FOUNDRY) fmt
