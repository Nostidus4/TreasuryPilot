# [TREASURY] Support multiple treasuries with a consolidated view

| Field | Value |
|---|---|
| **ID** | TRS-L01 |
| **Epic** | M02 · Treasury & Chain Configuration |
| **Module** | `treasury` ([spec](../../../docs/modules/treasury/README.md)) |
| **Phase / Priority** | Later / - |
| **Size** | L (1.5–2 days; split if it grows) |
| **Area** | backend |
| **Status** | Accepted |
| **Traces to** | FR-110 |
| **Blocks** | TRS-L02, EXE-L03 |
| **Submission cut** | After submission |

> **Phase: Later.** This ticket is intentionally coarser than M1 tickets. It must be re-estimated and split before it is scheduled.

## Context

This ticket belongs to the epic **Treasury & Chain Configuration**. It supports:

- F-014: Multi-treasury & multi-chain

Problem behind this work (from `docs/FEATURES.md`):

- **F-014** solves: Real businesses operate across chains.

## Objective

Operate treasuries on several chains from one org.

## Scope

- TRS-L01A (M): per-chain treasury registry
- TRS-L01B (M): isolate controls and counters per treasury
- TRS-L01C (S): consolidated view without cross-asset sums

## Out of scope

Nothing specific beyond the scope above.

## Technical notes

Follow the module spec and the relevant ADRs.

## Dependencies

- TRS-004: Implement treasury creation with Safe verification

## Acceptance criteria

- [ ] Counters and mandates are isolated per treasury

## Testing requirements

- Integration

## Re-estimate and implementation split

The original M estimate did not account for the registry contract, treasury isolation checks, and organization-wide view. Re-estimate the parent to L and schedule these three reviewable slices:

| Slice | Estimate | Scope | Depends on |
|---|---:|---|---|
| TRS-L01A · Per-chain treasury registry | M | Create and list an organization's treasuries across supported chains; preserve chain/asset integrity and tenant isolation. | TRS-004 |
| TRS-L01B · Treasury control isolation | M | Keep wallets, mandates, limits, coverage, requests, and counters scoped to one treasury; verify independent records in integration. | TRS-L01A |
| TRS-L01C · Consolidated portfolio view | S | Show one row per treasury with its own chain, asset, status, and controls; never combine values from different assets without a pricing source. | TRS-L01A, TRS-L01B |

Combined estimate: L (approximately 2–3 days). The parent acceptance criteria apply across all three slices.

## Definition of Done

- [ ] Code completed and merged through a reviewed PR
- [ ] Tests listed above pass in CI
- [ ] Docs / ADR updated if behaviour or design changed
- [ ] Money handled as integer base units; no business-critical rule depends on an LLM alone
