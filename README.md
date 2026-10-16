# TreasuryPilot

> An AI treasury operator that gets **approved** invoices paid on time. It moves liquidity between a company's own wallets and settles on-chain. A smart-contract mandate guarantees it can never pay the wrong party, exceed the budget, or touch the safety buffer.

**Humans decide whether to pay. The agent decides how and when. The contract makes sure it can't do anything else.**

Built for **FinTechathon 2026 – International Track, Topic F (Agent Wallet)**. Designed as a real multi-tenant product; Milestone 1 (M1) is the competition build.

- **GitHub repository:** https://github.com/Nostidus4/TreasuryPilot
- **Report hub (GitHub Pages):** https://nostidus4.github.io/TreasuryPilot/report/

> ⚠️ **Status: M1 competition build.** Runs on Anvil (local) and Ethereum Sepolia with test assets only. The contracts are unaudited. Do not use with real funds.

## What it does

1. **Intake:** upload an invoice (PDF, CSV or manual). AI extracts the fields and payment terms and flags fraud signals.
2. **Approve:** a human approver signs an EIP-712 approval over the exact payment fields.
3. **Plan:** a deterministic engine and an AI planner schedule payments to capture discounts and avoid late fees, within liquidity and limits.
4. **Execute:** the agent refills the paying wallet from the treasury wallet and pays the vendor through a Safe module that enforces the mandate on-chain.
5. **Verify and reconcile:** receipts, post-conditions, reconciliation export and an evidence bundle.

## Quick start (local)

Prerequisites: Docker + Compose, [uv](https://docs.astral.sh/uv/) 0.11.3, Node 22 + pnpm 9.15.9 (via corepack). Foundry v1.8.5 runs in Docker.

```bash
git clone https://github.com/Nostidus4/TreasuryPilot.git && cd TreasuryPilot
make bootstrap                              # uv sync + pnpm install --frozen-lockfile
cp infra/env/.env.example infra/env/.env    # runnable local defaults; ANTHROPIC_API_KEY is optional
make dev                                    # postgres, redis, minio, anvil, api, workers, beat, signer, web
make seed                                   # deploy contracts + Safes to Anvil, insert a TEST org, users, invoices
make smoke                                  # check web/API/infra endpoints
open http://localhost:5173
```

`make seed` prints the login links and addresses. `make scenario NAME=demo-main` replays the scripted demo (run `make scenario` to list scenarios); the walkthrough is in [`docs/demo-runbook.md`](docs/demo-runbook.md). Full guide: [`DEVELOPMENT.md`](DEVELOPMENT.md).

## Deployment

| Target | How |
|---|---|
| Local stack | `make dev` (Compose, `infra/compose.yaml`, profile `local`) |
| Contracts → Anvil | `make deploy-local` (`forge script script/Deploy.s.sol:Deploy --broadcast`) |
| Contracts → Sepolia | [`contracts/docs/DEPLOYMENT.md`](contracts/docs/DEPLOYMENT.md), then `make verify-sepolia` |
| Testnet VM (Sepolia, Caddy TLS) | `infra/scripts/deploy-testnet.sh <git-sha>` pulls the GHCR images published by `.github/workflows/images.yml`. Steps: [DEVELOPMENT.md → Deploying to a testnet VM](DEVELOPMENT.md#deploying-to-a-testnet-vm) |
| Supabase Postgres | `infra/compose.supabase.yaml` overlay, see [DEVELOPMENT.md](DEVELOPMENT.md#using-supabase-postgres) |
| Web + report on GitHub Pages | `.github/workflows/pages.yml` |

Sepolia (chain 11155111) addresses, from [`deployments/11155111.json`](deployments/11155111.json):

| Contract | Address |
|---|---|
| TreasuryPilotModule | `0xD90e961A1d7B68405Fa8b08F03F6917ada9798F5` |
| Factory | `0x80F14a69B3c01B7242D6C75c0414F3A5E72E115d` |
| Implementation | `0x9dbE3D17aa718d4808F410DCf80ffe2CFA6bE158` |
| Test token | `0xBbc291e8Bfed018b982646D6F80D3c8ffE4d84cd` |
| USDC (Aave test, 6 decimals) | `0x94a9D9AC8a22534E3FaCa9F4e7F2E2cf85d5E4C8` |

Known limit: the Aave test USDC supply cap was full at block 11890000, so the live Sepolia supply step can fail until headroom returns (see the manifest).

## Tests

| Suite | Command | Where |
|---|---|---|
| Everything | `make test` | Python + web + contracts |
| Python (pytest) | `make test-python` or `uv run pytest` | `packages/`, `services/`, `infra/scripts/tests` (`@pytest.mark.integration` needs Postgres/Anvil) |
| Web unit (Vitest) | `pnpm --dir apps/web test` | `apps/web/src` |
| Web e2e (Playwright) | `pnpm --dir apps/web e2e` · full stack: `pnpm --dir apps/web e2e:stack` | `apps/web/e2e/`, `apps/web/e2e-stack/` |
| Contracts (Foundry: unit, fuzz, invariant, fork, scenario, security) | `make test-contracts` | `contracts/test/` |
| Static analysis | `make slither` · `make lint` | `contracts/slither-report/` |
| AI evals (recorded, no key needed) | `make eval-validate` · `make eval-extraction` · `make eval-copilot` · `make eval-redteam` | `evals/` |
| Reliability | `make reliability` (30 local runs on Anvil) | [`docs/evidence/`](docs/evidence/) |

CI runs these in `.github/workflows/` (`ci.yml`, `web.yml`, `web-stack-e2e.yml`, `contracts.yml`, `contract-security.yml`, `contract-integration.yml`, `evals.yml`, `docker.yml`). Test evidence and rule-to-test mapping: [`docs/security/test-evidence.md`](docs/security/test-evidence.md), [`docs/security/contract-rule-test-mapping.md`](docs/security/contract-rule-test-mapping.md).

## Documentation map

| Read this | For |
|---|---|
| [Technical report (EN)](docs/TECHNICAL_REPORT_EN.md) · [Tiếng Việt](docs/TECHNICAL_REPORT_VI.md) · [简体中文](docs/TECHNICAL_REPORT_ZH.md) · [Pages hub](https://nostidus4.github.io/TreasuryPilot/report/) | Trilingual, page-by-page technical report with implementation evidence; English is the default |
| [Nine-part report (EN)](docs/PRODUCT_REPORT_EN.md) · [DOCX](docs/TreasuryPilot_Product_Technical_Report_EN.docx) · [Slide visuals](docs/TreasuryPilot_Slide_Assets.zip) | Shareable product/technical report and editable slide-ready architecture images |
| [`docs/PROJECT_OVERVIEW.md`](docs/PROJECT_OVERVIEW.md) ([Tiếng Việt](docs/vi/01-tong-quan.md)) | Product, problem, users, journeys |
| [`docs/FEATURES.md`](docs/FEATURES.md) | 99 features with full specs |
| [`docs/FUNCTIONAL_REQUIREMENTS.md`](docs/FUNCTIONAL_REQUIREMENTS.md) · [`NON_FUNCTIONAL_REQUIREMENTS.md`](docs/NON_FUNCTIONAL_REQUIREMENTS.md) · [`BUSINESS_RULES.md`](docs/BUSINESS_RULES.md) | Requirements and rules |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) → [`docs/SYSTEM_ARCHITECTURE.md`](docs/SYSTEM_ARCHITECTURE.md) | Architecture |
| [`docs/TECH_STACK.md`](docs/TECH_STACK.md) · [`docs/adr/`](docs/adr/README.md) | Stack and decisions |
| [`docs/AI_AGENT_ARCHITECTURE.md`](docs/AI_AGENT_ARCHITECTURE.md) | What the AI may and may not do |
| [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) · [`docs/API_SPEC.md`](docs/API_SPEC.md) | Data and API |
| [`docs/modules/`](docs/modules/README.md) | 20 module specs |
| [`docs/submission/`](docs/submission/README.md) | Hackathon submission: technical documentation, security self-assessment, compliance, licenses |
| [`planning/BACKLOG.md`](planning/BACKLOG.md) · [`planning/issues/`](planning/issues/) | Epics and ticket drafts |
| [`docs/OPEN_QUESTIONS.md`](docs/OPEN_QUESTIONS.md) · [`docs/decisions-log.md`](docs/decisions-log.md) | Open points and decisions |

## Repository layout

See [`docs/REPOSITORY_STRUCTURE.md`](docs/REPOSITORY_STRUCTURE.md). In short: `apps/web` (Vite + React), `services/api` (FastAPI), `services/worker` (Celery planner, executor, AI agent), `services/signer`, `packages/py-core` (pure domain core), `contracts` (Foundry/Solidity, Safe module), `infra` (Compose, Caddy, scripts), `deployments` (chain manifests), `evals`, `scenarios`.

Contribution rules are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security

Trust boundaries and the known-risk list are in `docs/SYSTEM_ARCHITECTURE.md` §3 and [`docs/security/`](docs/security/known-risks.md) and the [security self-assessment](docs/submission/security-self-assessment.md). Please report vulnerabilities privately to the maintainers. Do not open public issues for them.

## License

[MIT](LICENSE). Third-party licenses: [`docs/submission/licenses.md`](docs/submission/licenses.md).
