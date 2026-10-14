# ADR-003: EIP-712 for approvals, exceptions and plan attestations
**Status:** Accepted (G2, 2026-10-11) · **Rules:** BR-003, BR-004, BR-041, BR-059

## Context
Human authority (approve, grant exception) and system authority (validated plan) must be bound to exact fields, verifiable on-chain and replay-safe.

## Revision (M04 grilling, 2026-10-11)
`OneTimeException` and the duplicate-override flag are **no longer EIP-712 signatures**. The Owner (Safe T) grants them with governance transactions `grantException(...)` and `allowDuplicate(...)` (M04-D3). On-chain, only `PaymentApproval` remains a typed signature in M1; `PlanAttestation` stays signer-side.

## Original decision

The current PaymentApproval has 13 fields per ADR-019. Signer-side
PlanAttestation uses the separate `TreasuryPilot Policy` domain defined in M08
section 6.3; SC-017 publishes vectors for it. The original signatures below are
historical, including the superseded on-chain exception and duplicate flag.
Three typed structs, each under the domain `{name: "TreasuryPilot", version: "1", chainId, verifyingContract: module}`:
- `PaymentApproval{requestId, invoiceHash, fingerprint, treasury, payingWallet, asset, payee, amount, deadline, termsHash, overrideDuplicate, expiry}`. Signed by an Approver; verified on-chain.
- `OneTimeException{requestId, mandateVersion, payingWallet, payee, asset, amount, expiry, nonce}`. Signed by the Owner; verified on-chain, consumed once.
- `PlanAttestation{planHash, requestId, stepIds[], policyVersion, executor, validUntil, nonce, evidenceDigest}`. Signed by the policy-engine key; verified by the signer service in M1, and on-chain by `PlanAttestedExecutor` (SC-L04, opt-in).

ERC-1271 is supported for contract-wallet signers. Nonces and used-flags provide replay protection, because EIP-712 alone does not (GA p.22).

## Alternatives
- On-chain approval registry transactions: each approval costs gas and a transaction.
- Backend flags only: violates BR-004.

## Consequences
- Canonical encoding is shared between Python (eth-account) and TS (viem). Golden test vectors are kept in `contracts/test/vectors`.
