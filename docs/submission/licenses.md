# Third-party license inventory

**Tracking:** #239 / DOM-015 · **Traces to:** NFR-CMP-03

This inventory covers **direct dependencies only** (not transitive ones), as
installed on 2026-10-15 from the lockfiles. Licenses were read from installed
package metadata. Rows marked "upstream" are not read from the artifact: they
are the upstream project's published license and need a human check before
submission. This is not legal advice.

## Repository license

No `LICENSE` file exists yet. The license of this repository's own code is
**pending**: it is decided separately in #241 and is not set by this note.

## Python (`pyproject.toml`, `uv.lock`)

| Package | Version | License |
| --- | --- | --- |
| abnf | 2.2.0 | MIT |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT |
| alembic | 1.20.0 | MIT |
| anthropic | 1.13.0 | MIT |
| asyncpg | 0.32.0 | Apache-2.0 |
| celery | 5.6.3 | BSD-3-Clause |
| cryptography | 46.0.7 | Apache-2.0 OR BSD-3-Clause |
| eth-abi | 5.2.0 | MIT |
| eth-account | 0.13.7 | MIT |
| eth-hash | 0.8.0 | MIT |
| fastapi | 0.143.0 | MIT |
| httpx2 | 2.13.1 | BSD-3-Clause |
| hypothesis | 6.169.0 | MPL-2.0 |
| import-linter | 2.3 | BSD-2-Clause |
| minio | 7.2.18 | Apache-2.0 |
| mypy | 1.20.2 | MIT |
| opentelemetry-api | 1.45.1 | Apache-2.0 |
| opentelemetry-exporter-otlp-proto-http | 1.45.1 | Apache-2.0 |
| opentelemetry-instrumentation-celery | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-fastapi | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-httpx | 0.66b1 | Apache-2.0 |
| opentelemetry-instrumentation-sqlalchemy | 0.66b1 | Apache-2.0 |
| opentelemetry-sdk | 1.45.1 | Apache-2.0 |
| ortools | 9.14.6206 | Apache-2.0 |
| pillow | 11.3.0 | MIT-CMU |
| pre-commit | 4.2.0 | MIT |
| prometheus-client | 0.26.0 | Apache-2.0 AND BSD-2-Clause |
| pydantic | 2.14.0 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| pypdf | 5.9.0 | BSD-3-Clause |
| pysaml2 | 7.5.5 | Apache-2.0 |
| pytest | 8.3.5 | MIT |
| pytest-cov | 6.3.0 | MIT |
| python-multipart | 0.0.32 | Apache-2.0 |
| pyyaml | 6.0.3 | MIT |
| redis | 6.4.0 | MIT |
| ruff | 0.11.13 | MIT |
| sentry-sdk | 2.72.0 | MIT |
| siwe | 4.4.0 | MIT OR Apache-2.0 (License field; classifier says Other/Proprietary) |
| sqlalchemy | 2.1.4 | MIT |
| structlog | 25.5.0 | MIT OR Apache-2.0 |
| types-pyyaml | 6.0.12.20260906 | Apache-2.0 |
| uvicorn | 0.54.0 | BSD-3-Clause |
| web3 | 7.16.0 | MIT |

Notes: `hypothesis` is MPL-2.0 (file-level copyleft; used unmodified).
Dev-only packages: httpx2, hypothesis, import-linter, mypy, pre-commit, pytest,
pytest-cov, ruff, types-pyyaml.

## Web (`apps/web/package.json`, `pnpm-lock.yaml`)

| Package | Version | License |
| --- | --- | --- |
| @fontsource-variable/ibm-plex-sans | 5.3.0 | OFL-1.1 |
| @fontsource/ibm-plex-mono | 5.3.0 | OFL-1.1 |
| @hookform/resolvers | 3.10.0 | MIT |
| @rainbow-me/rainbowkit | 2.2.11 | MIT |
| @sentry/react | 11.7.0 | MIT |
| @tanstack/react-query | 5.104.1 | MIT |
| @tanstack/react-table | 8.21.3 | MIT |
| class-variance-authority | 0.7.1 | Apache-2.0 |
| clsx | 2.1.1 | MIT |
| cmdk | 1.1.1 | MIT |
| date-fns | 4.4.0 | MIT |
| i18next | 26.4.3 | MIT |
| lucide-react | 0.468.0 | ISC |
| openapi-fetch | 0.14.1 | MIT |
| radix-ui | 1.7.0 | MIT |
| react, react-dom | 18.3.1 | MIT |
| react-dropzone | 20.1.3 | MIT |
| react-hook-form | 7.89.0 | MIT |
| react-i18next | 17.0.16 | MIT |
| react-resizable-panels | 4.14.4 | MIT |
| react-router-dom | 6.30.6 | MIT |
| recharts | 2.15.4 | MIT |
| sonner | 2.0.8 | MIT |
| tailwind-merge | 2.6.1 | MIT |
| vaul | 1.1.2 | MIT |
| viem | 2.57.4 | MIT |
| wagmi | 2.19.5 | MIT |
| zod | 3.25.76 | MIT |
| @playwright/test (dev) | 1.64.0 | Apache-2.0 |
| axe-core (dev) | 4.10.2 | MPL-2.0 (file-level copyleft; used unmodified) |
| typescript (dev) | 5.9.3 | Apache-2.0 |
| tailwindcss, tailwindcss-animate, postcss, autoprefixer (dev) | 3.4.17 / 1.0.7 / 8.5.29 / 10.6.1 | MIT |
| eslint, @eslint/js, eslint-plugin-react-hooks, eslint-plugin-react-refresh, globals, typescript-eslint (dev) | 9.39.5 / 9.39.5 / 5.2.0 / 0.4.26 / 15.15.0 / 8.71.1 | MIT |
| vite, @vitejs/plugin-react, vitest, jsdom, msw (dev) | 8.3.4 / 6.1.2 / 4.1.11 / 26.1.0 / 2.15.0 | MIT |
| @testing-library/jest-dom, react, user-event (dev) | 6.10.0 / 16.3.3 / 14.6.7 | MIT |
| openapi-typescript (dev) | 7.13.0 | MIT |
| @types/node, @types/react, @types/react-dom (dev) | 22.20.5 / 18.3.31 / 18.3.7 | MIT |
| prettier (root, dev) | 3.5.3 | MIT |

## Contracts (`contracts/package.json`, `contracts/foundry.toml`)

Solidity libraries come from npm via `libs = ["node_modules"]` and the
remappings in `foundry.toml`. There is no `contracts/lib` git submodule.

| Package | Version | License |
| --- | --- | --- |
| @openzeppelin/contracts | 5.2.0 | MIT |
| @safe-global/safe-contracts | 1.4.1 | LGPL-3.0 |
| ethers (dev, test tooling) | 5.4.0 | MIT |

`Safe.sol` is compiled from the unmodified `@safe-global/safe-contracts` package
(LGPL-3.0); legal review should confirm the obligations for redistributing its
bytecode.

## Docker images (`infra/compose.yaml`, Dockerfiles)

| Image | Use | License (upstream) |
| --- | --- | --- |
| postgres:16-alpine | database | PostgreSQL License |
| redis:7-alpine | broker/cache | Floating tag. BSD-3-Clause up to 7.2.x; the current 7.x tag resolves to the 7.4+ range (RSALv2/SSPLv1); Redis 8+ adds AGPL-3.0 as an option. Recommend pinning to 7.2.x or switching to valkey. Based on upstream knowledge, not a pulled image. |
| ghcr.io/foundry-rs/foundry:v1.8.5 | Anvil, forge | MIT OR Apache-2.0 |
| jaegertracing/jaeger:2.22.0 | tracing | Apache-2.0 |
| MinIO `RELEASE.2025-04-22T22-12-26Z`, built from source (`infra/minio/Dockerfile`) | object storage | AGPL-3.0 |
| python:3.12.13-slim-bookworm / -alpine | api, worker, signer, minio-init bases | PSF-2.0 (plus Debian/Alpine package licenses) |
| ghcr.io/astral-sh/uv:0.11.3 | build stage | MIT OR Apache-2.0 |
| node:22.22.0-alpine | web build stage | MIT |
| nginx:1.27.4-alpine | web runtime | BSD-2-Clause |
| golang:1.24.2-alpine3.21, alpine:3.21 | MinIO build and runtime | BSD-3-Clause (Go), Alpine packages vary |
| treasurypilot-slither (`contracts/docker/slither.Dockerfile`) | static analysis | Slither: AGPL-3.0 (upstream) |

## Models and AI providers (`config/ai.yaml`, `services/worker`)

| Item | Use | Terms |
| --- | --- | --- |
| Anthropic Claude (`claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`) via the `anthropic` SDK | Advisory planning and extraction (ADR-005) | Hosted API under Anthropic's commercial terms; no model weights are redistributed |
| Same models via AWS Bedrock (failover provider `bedrock`) | Failover | AWS service terms plus Anthropic's terms |

No open-weight model is bundled.

## Datasets, fonts and other assets

| Item | Source | License / status |
| --- | --- | --- |
| `evals/` invoices, planner scenarios, red-team and Copilot cases | Authored by the team (synthetic, labelled) | Team-owned; follows the repository license once #241 decides it |
| Sanctions fixture (`screening_lists`, migration `20261014_0013`) | Team test entries plus a sample of addresses from the [OFAC SDN update of 2026-03-12](https://ofac.treasury.gov/recent-actions/20260312) | TEST DATA; US government publication. Confirm reuse terms before redistribution |
| IBM Plex Sans (variable) and IBM Plex Mono, via `@fontsource` | `apps/web/src/main.tsx` | SIL OFL-1.1 |
| lucide-react icons | npm | ISC |

No other datasets, images or fonts are tracked in git (checked with `git ls-files`).

## Regenerate

Python (direct dependencies of every workspace member):

```sh
uvx uv@0.11.3 run --all-packages --group dev python - <<'PY'
import importlib.metadata as m, re, tomllib
files = ["pyproject.toml", "packages/py-core/pyproject.toml", "services/api/pyproject.toml",
         "services/signer/pyproject.toml", "services/worker/pyproject.toml"]
names = set()
for f in files:
    d = tomllib.load(open(f, "rb"))
    deps = list(d["project"].get("dependencies", []))
    for g in d.get("dependency-groups", {}).values():
        deps += [x for x in g if isinstance(x, str)]
    names |= {re.split(r"[\[<>=!~ ;]", x, 1)[0].lower() for x in deps}
for n in sorted(names):
    if n.startswith("treasurypilot"):
        continue
    md = m.metadata(n)
    print(n, md["Version"], md.get("License-Expression") or md.get("License") or "")
PY
```

Web and contracts:

```sh
corepack pnpm@9.15.9 install --frozen-lockfile
node -e 'for (const d of [".", "apps/web", "contracts"]) {
  const p = require("./" + d + "/package.json");
  for (const n of Object.keys({...p.dependencies, ...p.devDependencies}))
    console.log(d, n, require("./" + d + "/node_modules/" + n + "/package.json").license);
}'
```

Docker images: `grep -rE "image:|^FROM" infra services apps contracts/docker`. Re-run
after any dependency change and before the final submission.
