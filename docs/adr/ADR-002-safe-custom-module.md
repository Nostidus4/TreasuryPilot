# ADR-002: Safe + custom TreasuryPilotModule, one instance per treasury
**Status:** Accepted (G2, 2026-10-11) · **Decision:** Q26 · **Rules:** BR-010–BR-030, BR-040–BR-042, BR-071, BR-090–091

## Context
Enforcement must be on-chain (AP-1). The rules include EIP-712 approval verification, payee cooling, fingerprints, buffers, treasury-wide UTC counters and one-time exceptions. Customer funds stay in customer-owned Safes (BR-091).

## Decision
- Deploy one `TreasuryPilotModule` per treasury and enable it on Safes T, O1 and O2.
- The module executes only typed actions (`refill`, `pay`, `swapForGas`) through `execTransactionFromModule` on the relevant Safe. `swapForGas` carries no attestation: its `minOut` is accepted unattested for the TEST ROUTER only (fixed rate, on-chain perRequest/daily caps); production swaps need `minOut` in the attestation or an on-chain price floor (execution README, EXE-011-D1). `SignedQuoteSwapAdapter` (SC-L03) supplies that floor on-chain as the signed quote's `minAmountOut`, enforced against the measured output delta.
- Governance functions are callable only by Safe T itself (the Owner signs a Safe transaction). `pause` is also callable by the Guardian.
- The module is not upgradeable in M1. Changing it means a disable/enable by the Owner.
- Coverage verification (F-012) checks that no other module is enabled.

## Revision (M04 grilling)
- Modules are **EIP-1167 clones** created by `TreasuryPilotModuleFactory`; `create` is called by Safe T itself, which initializes the clone in the same transaction (M04-D2, M04-D9).
- Safe **v1.4.1** pinned (M04-D1). No native-token transfers in M1 (M04-D10).

## Alternatives
- **Zodiac Roles Modifier:** cannot express the rules above.
- **Safe Guard:** guards do not cover module execution paths (GA p.4).
- **ERC-4337/7579 + session keys:** bundler and paymaster complexity, less mature tooling in Python.
- **One module per Safe:** cannot share treasury-wide counters without cross-contract calls.

## Consequences
- The module is critical, unaudited code; it needs invariant/fuzz tests and Slither (F-163).
- `approve` must be executed by the Safe, not the module (GA p.23).
- Return data must be checked (`execTransactionFromModuleReturnData`).
