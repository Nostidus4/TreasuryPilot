# M08 · Policy Engine & Attestation

**Status:** Draft for gate G2 · **Path:** `docs/modules/policy-engine/`

## Purpose
Deterministic validator mirroring the contract checks; ALLOW/NEEDS_APPROVAL/BLOCK with reason codes; builds and signs PlanAttestation.

## Features
F-055, F-056

## Inputs
Plan, snapshot, mandate, approvals, exceptions, operation states.

## Outputs
Validation records; attestations.

## APIs
Package API: `validate(plan, ctx) -> Decision`; worker-side `attest(plan) -> Attestation` (uses the policy signing key, separate from the executor key).

## Data model
validations, attestations

## Dependencies
M07, M05, M03, M06.

## Security concerns
Validator/contract drift (differential tests on AT-05 cases); attestation key protection (separate secret, held by the worker's policy component only).

## Failure scenarios
Missing data → BLOCK (never ALLOW).

## Open questions
Whether to also verify attestations on-chain (Later).
