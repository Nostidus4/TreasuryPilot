# Reproducible scenarios

One YAML file per named scenario (DEV-007). Run with:

```sh
uv run python infra/scripts/scenario.py list
uv run python infra/scripts/scenario.py run pause    # needs `make dev` and `make deploy-local`
```

Fields: `name` (= file name), `adr019` (D-id), `chain_id` (must be in the allowlist: 31337, 11155111;
the live RPC chain id must match, mainnet is refused), `requires` (capabilities), `steps`, `must_show`.

A scenario whose `requires` lists a capability the runner does not provide yet is reported as
`NOT_RUNNABLE` (exit 2) and writes no evidence bundle. Capabilities currently provided: `anvil`,
`deployment`. Pending: `planner` (#146), `sequencer` (#65), `executor-pipeline`,
`ai-extraction`, `outbox-recovery`, `chain-reader-alerts`, `fee-policy-runtime`.

Each run writes `docs/evidence/scenarios/<name>-<UTC time>/run.json` and `evidence-bundle.json`
(evidence-bundle.v1, validated before writing). Only `pause` is runnable today; D2, D3, D6-D8 have
no scenario file yet.
