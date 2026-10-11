# Contract implementation notes

The implementation follows M04 section 15 and ADR-019 when they supersede older issue text. Solidity is 0.8.28, as pinned by the existing Foundry foundation.

## Interfaces and errors (#28)

`ITreasuryPilotModule` defines the 13-field `PaymentApproval`, complete governance/executor interfaces, and indexed lifecycle events. `TreasuryPilotStorage` contains independent per-clone state. PAY, REFILL, SWAP_IN and SUPPLY use action ids 1, 2, 3 and 4 respectively; the sole asset is implicit in `keccak256(abi.encode(action, day))` within each module.

Errors are in `TreasuryPilotErrors` because Solidity cannot declare an event and error with the same identifier in one scope. This preserves the specified `RequestCancelled()` and `Revoked()` error selectors and the `RequestCancelled(bytes32,address)` and `Revoked()` events. Consumers should use the module's compiled ABI and match error selectors rather than source qualification.

`PaymentApprovalHash` has exactly one EIP-712 type. Exceptions and duplicate allowances are Safe governance calls, not typed signatures. The obsolete OneTimeException and PlanAttestation vectors in SC-017 are superseded by M04-D3 and ADR-019.

Approval signatures use `abi.encode(address approver, bytes signature)`. The explicit identity supports arbitrary ERC-1271 signature lengths and distinguishes removed approvers (`NotApprover`) from invalid signatures (`ApprovalInvalid`). EIP-712 cannot distinguish field mutations, wrong chain and wrong signing domain from the signature alone; all invalid cryptographic proofs use `ApprovalInvalid`, as required by M04 section 6.4.
