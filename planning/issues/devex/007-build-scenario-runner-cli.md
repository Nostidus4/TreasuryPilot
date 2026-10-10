# [DEVEX] Build scenario runner CLI

| Field | Value |
|---|---|
| **ID** | DEV-007 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | M (~1 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | FR-929, BR-095 |
| **Blocks** | DEV-008, DEV-009 |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-162: Scenario runner & demo runbook

Problem behind this work (from `docs/FEATURES.md`):

- **F-162** solves: Reliable demos and evidence.

## Objective

Named scenarios can be reset and replayed, each producing an evidence bundle.

## Scope

- CLI `scenario run <name>` and `scenario list`
- scenarios: demo-main, over-cap-exception, injected-invoice, crash-recovery, pause
- chain-id allowlist check
- export evidence bundle per run

## Out of scope

Reliability loop (DEV-009).

## Technical notes

Scenario definitions as YAML in scenarios/. Refuse chain ids not in the allowlist.

## Dependencies

- DEV-006: Write seed script for the local environment
- AUD-003: Define the evidence bundle schema and exporter

## Acceptance criteria

- [ ] Each named scenario runs end to end on Anvil
- [ ] A mainnet chain id is refused with a clear error
- [ ] Each run writes an evidence bundle that validates against its schema

## Testing requirements

- Integration: run demo-main in CI on Anvil

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
