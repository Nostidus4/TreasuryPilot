# ADR-020: On-chain reserves and execution holds as an external executor

**Status:** Accepted (2026-10-15) · **Issue:** #86 (SC-L01, F-028, BR-035) · **Code:** `contracts/src/ReserveHoldExecutor.sol`

## Context
Funds approved for one payment request must not be spendable by another request (F-028, BR-035). The module enforces a per-wallet buffer and mandate limits but has no notion of funds promised to a specific request. `TreasuryPilotModule` is about 100 bytes under the EIP-170 limit (24,576 bytes), so new storage and checks cannot go into it without a risky size cut, and its ABI and storage layout are consumed by the Python backend and web app (ADR-002, ADR-016).

## Decision
1. **External executor.** `ReserveHoldExecutor(module, operator)` is set as `mandate.executor` of the module by Safe T. It keeps `commitments[requestId] = {asset, wallet, reserved, held}` and totals `reservedOf` / `heldOf` per `(asset, wallet)`. Every spend (`pay`, `refill`, `supply`, `swapForGas`, `repay`) is forwarded to the module and then checked: `balance(wallet) >= bufferOf + reserved + held`, else `CommittedFundsBreach`. `withdraw` and `borrow` only add cash to Safe T and pass through. The module is unchanged. The same pattern as `PlanAttestedExecutor` (ADR-016); composing the two is not tested and is not claimed.
2. **R to L semantics.** Approval reserves R (`reserve`, fails with `InsufficientUncommitted` if `balance - buffer - committed < amount`, which the backend reports as a funding deficit). Execution start moves the whole R to L (`beginExecution`); the committed total does not change, so nothing is counted twice. Payment of the request clears its commitment. A hold is never released by a timeout.
3. **Operator trust model.** The immutable `operator` is the module's executor today and is already trusted to choose among approved payments. It can create and advance commitments but not free them at will: the operator may `release` only when the module shows the request paid or cancelled. The Safe T owner may `release` any commitment unconditionally (declaring the outcome failed) and may clear many at once with `releaseMany(bytes32[])` (unregistered ids are skipped). Rotating the operator means deploying a new executor and calling `configureMandate`.
4. **`pay` ordering.** Checks, effects, interactions: the paid request's own commitment is cleared and `Released` emitted before `module.pay`, then `_enforce` runs. The commitment is cleared only if `commitment.wallet == ap.payingWallet`. A commitment on another wallet is left in place (freeing it would not free the funds this payment spends, and leaving it is the safer failure); it stays until `release`, which the operator may then call because the module shows the request paid.

## Alternatives
- **Put R/L into the module:** does not fit under EIP-170 and changes the ABI and storage layout.
- **Off-chain only (status quo):** the backend validator can be bypassed or raced; the contract is the authority over money (AP-1).
- **Timeout release of holds:** rejected; a hold on an unknown outcome must not unlock funds that may already have been sent.
- **Operator may release freely:** rejected in review; a compromised operator could free R and spend it.

## Consequences
- Opt-in per treasury; Safe T gains protection only for spends routed through the executor. A direct Safe transaction by the owner is outside the module and not covered.
- Invariants R1 (reserved + held never exceeds balance minus buffer on the executor path), R2 (totals equal the per-request ledger) and R3 (R to L and release rules) are in `test/invariant/ReserveHoldInvariant.t.sol`.

## Known gaps
- **Squatting and griefing.** The operator can reserve capacity on any operational wallet (`reserve` with arbitrary ids) and can register an id for a request that never executes, locking that capacity; the id cannot be reused. Only the owner can clear it, via `release` or `releaseMany`. This is a denial of liquidity, not theft. Operational monitoring should alert on commitments older than the expected approval-to-payment window.
- **Debt-service reserve and the full off-chain `PaymentReserve`** (ADR-019 formulas) are not enforced on-chain; only per-request R/L commitments plus the module buffer are.
- Commitment amount is not tied to the paid amount: paying more than the reserved amount is bounded only by the post-call check against other commitments.
- Deploy script and backend integration (reserve on approval, beginExecution on start, release on outcome, funding-deficit reporting) are not part of this change.
- `tools/check_mutations.py` is hard-wired to the module and `TreasuryInvariantTest`; mutation checks for this contract's `_enforce` are not added.
