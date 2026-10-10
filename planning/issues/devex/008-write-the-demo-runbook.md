# [DEVEX] Write the demo runbook

| Field | Value |
|---|---|
| **ID** | DEV-008 |
| **Epic** | M19 · Developer Experience & Quality |
| **Module** | `devex` ([spec](../../../docs/modules/devex/README.md)) |
| **Phase / Priority** | M1 / P1 |
| **Size** | S (≤ 0.5 day) |
| **Area** | infrastructure |
| **Status** | Ready for Review |
| **Traces to** | — |
| **Blocks** | DOM-014 |

## Context

This ticket belongs to the epic **Developer Experience & Quality**. It supports:

- F-162: Scenario runner & demo runbook

Problem behind this work (from `docs/FEATURES.md`):

- **F-162** solves: Reliable demos and evidence.

## Objective

A step-by-step runbook so anyone on the team can run the 5-minute demo reliably.

## Scope

- docs/demo-runbook.md: setup and reset steps, each scene mapped to a scenario, expected screen, fallback if a step fails, evidence to capture

## Out of scope

Recording the video (DOM-014).

## Technical notes

Follow the 9-scene script in docs/research/TreasuryPilot-Ke-hoach-nang-diem-80-90.md §7.

## Dependencies

- DEV-007: Build scenario runner CLI

## Acceptance criteria

- [ ] Every scene references a scenario name
- [ ] A teammate who did not write it completes a dry run using only the runbook

## Testing requirements

- Manual: one dry run by a second person

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
