# M04 · Smart Contracts

**Status:** Draft for gate G2 · **Path:** `docs/modules/contracts/`

## Purpose
On-chain enforcement: TreasuryPilotModule (mandate, payees, approvals, counters, buffers, exceptions, replay protection, pause), test token, test router (P2), deployment scripts, EIP-712 vectors.

## Features
On-chain parts of F-012, F-021–F-026, F-037, F-038, F-062–F-064, F-074; F-163 contract suites

## Inputs
Governance calls from Safe T; executor calls carrying approvals, exceptions and attestations.

## Outputs
Token transfers via Safes; events (`MandateConfigured`, `PayeeAdded`, `RefillExecuted`, `PaymentExecuted`, `ExceptionConsumed`, `Paused`, `Resumed`, `Revoked`); revert codes matching API error codes.

## APIs
Solidity interface (see the section below).

## Data model
On-chain storage: mandate struct, payees mapping(address→activeFrom,status), approvers set, counters mapping(bytes32 key→uint256), used requestIds/stepIds/fingerprints, exception nonces.

## Dependencies
Safe contracts (pinned), OpenZeppelin (ECDSA/EIP712/SignatureChecker). No off-chain dependency.

## Security concerns
This is the critical path. Covered threats: reentrancy (checks-effects-interactions + guard); signature malleability and replay (EIP-712 + nonces + used flags); token returning false (check return data); approve race (exact amount → 0); generic execution (none exposed); governance spoofing (`msg.sender == safeT`); daily window edge (block.timestamp day key); integer overflow (0.8 checked math).

## Failure scenarios
A revert must leave no partial state. A Safe call failure must revert the whole module call.

## Open questions
ADR-012 chain (Phúc). Whether plan attestations are verified on-chain in M1 (default: signer-side only).

## Interface (draft)

```solidity
interface ITreasuryPilotModule {
  // governance: only Safe T (Owner via Safe tx)
  function configureMandate(Mandate calldata m) external;          // version++, invalidates exceptions
  function setApprovers(address[] calldata a) external;
  function addPayee(address payee, uint64 coolingSeconds) external; // activeFrom = now + cooling
  function deactivatePayee(address payee) external;
  function resume() external;
  function revoke() external;
  // emergency: Safe T or guardian
  function pause() external;
  // executor only
  function refill(PaymentApproval calldata ap, bytes calldata apSig, bytes32 stepId,
                  address toWallet, uint256 amount) external;
  function pay(PaymentApproval calldata ap, bytes calldata apSig,
               OneTimeException calldata ex, bytes calldata exSig, bytes32 stepId) external;
  function swapForGas(SwapParams calldata p, bytes32 stepId) external; // P2, test router only
  // views
  function used(bytes32 id) external view returns (bool);
  function counter(uint8 action, address asset, uint256 day) external view returns (uint256);
  function payeeStatus(address payee) external view returns (uint8 status, uint64 activeFrom);
}
```

**Invariants (F-163, at least 8):**
1. No PAY without a valid approver signature over the exact fields.
2. PAY only to an active payee whose cooling has ended.
3. Σ successful PAY per (asset, UTC day) ≤ the daily limit.
4. No agent-path transaction leaves a wallet below its buffer.
5. Each requestId, fingerprint and stepId executes at most once.
6. An exception lifts only the per-request cap and is consumed once.
7. Paused or revoked → every executor call reverts.
8. Version changes never reset counters.
9. Only Safe T changes governance; the guardian can only pause.
