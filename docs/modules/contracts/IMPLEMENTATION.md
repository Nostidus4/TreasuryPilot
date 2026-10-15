# Contract implementation notes

The implementation follows M04 section 15 and ADR-019 when they supersede older issue text. Solidity is 0.8.28, as pinned by the existing Foundry foundation.

## Interfaces and errors (#28)

`ITreasuryPilotModule` defines the 14-field `PaymentApproval`, complete governance/executor interfaces, and indexed lifecycle events. `TreasuryPilotStorage` contains independent per-clone state. PAY, REFILL, SWAP_IN and SUPPLY use action ids 1, 2, 3 and 4 respectively; the sole asset is implicit in `keccak256(abi.encode(action, day))` within each module.

Errors are in `TreasuryPilotErrors` because Solidity cannot declare an event and error with the same identifier in one scope. This preserves the specified `RequestCancelled()` and `Revoked()` error selectors and the `RequestCancelled(bytes32,address)` and `Revoked()` events. Consumers should use the module's compiled ABI and match error selectors rather than source qualification.

`PaymentApprovalHash` has exactly one on-chain EIP-712 type. Exceptions and duplicate allowances are Safe governance calls, so OneTimeException vectors are obsolete (M04-D3). PlanAttestation remains signer-side in M1: SC-017 publishes its vectors under `TreasuryPilot Policy` per M08 section 6.3. A test-only Solidity oracle verifies its array encoding, large nonce, hashes, signature and domain separation; the module itself does not verify policy attestations. SC-L04 adds `PlanAttestedExecutor`, an opt-in executor contract that does (see the module spec section 16).

Approval signatures use `abi.encode(address approver, bytes signature)`. The explicit identity supports arbitrary ERC-1271 signature lengths and distinguishes removed approvers (`NotApprover`) from invalid signatures (`ApprovalInvalid`). EIP-712 cannot distinguish field mutations, wrong chain and wrong signing domain from the signature alone; all invalid cryptographic proofs use `ApprovalInvalid`, as required by M04 section 6.4.

## Safe execution and governance

`TreasuryPilotModuleFactory` is immutable and creates EIP-1167 clones atomically. Every configured wallet must expose the initialized Safe owner/threshold interface. Safe T is always the factory caller. Initialization requires one explicit buffer entry per known wallet, rejects duplicate entries and operational wallets, and verifies both the Aave reserve mapping and the aToken's underlying asset and pool.

Owner changes go through Safe T; guardian authority is pause only. Revocation is permanent even when a new mandate is configured. Current approvers can permanently cancel unpaid requests in any status. All mutable module functions use OpenZeppelin's reentrancy guard, including initialization and governance.

The deployment path uses `createDeterministic` and `predictDeterministicAddress` with a salt namespaced by the calling Safe. Other CREATE traffic or another Safe using the same public salt cannot consume that address. The ordinary `create` interface remains available. Reusing a deterministic salt on the same Safe reverts before deployment; initialization remains atomic and storage stays independent.

PAY and REFILL use fixed ERC20 transfers with zero native value and `Enum.Operation.Call`. Both source and recipient deltas are checked exactly, and floors are rechecked after interaction. Each counter is treasury-wide and survives configuration changes. Early payments use the early amount through the inclusive `earlyPayBy` boundary. REFILL remains bounded by the standard amount plus the destination target.

SUPPLY/WITHDRAW only use the initialized pool, asset, aToken and Safe T. Supply has independent limits and preserves the static Safe floor; dynamic invoice reserves remain the off-chain validator's responsibility (ADR-019 V3-8). Approvals are exact and cleared to zero, and withdrawal validates the returned amount and cash delta.

P2 BORROW/REPAY each consume an owner grant once. `planId` must be the hash of the full immutable owner-reviewed plan, including snapshot, fixed pool/asset, maximum cost and repayment plan (BR-044). New parameters require a new plan hash. Borrow validates the variable rate and health factor immediately before and after execution; it cannot guarantee future rates. Repay cannot consume more than its approved amount and clears the residual allowance after a partial debt repayment.

P2 `swapForGas` is a test-only fixed ERC20 pair. Output stays in Safe T, budgets and floor apply, and no native gas token is transferred. Executor gas remains manually funded. The optional router is disabled until explicitly configured by Safe T.

`approvalMaxAge` is off-chain approval-building configuration: the signed schema has no `signedAt`, so the contract can enforce `expiry` but cannot independently infer signature age.

## Compiler profiles

The module uses Solidity 0.8.28's IR optimizer to remain below EIP-170. Safe 1.4.1 keeps its legacy compiler pipeline because its upstream assembly is incompatible with IR. Foundry compilation restrictions apply IR to the module and its importers; Safe artifacts are compiled separately and deployed by tests via `vm.getCode`. No upstream Safe source is patched. See [Foundry compiler profiles](https://getfoundry.sh/reference/config/solidity-compiler).
