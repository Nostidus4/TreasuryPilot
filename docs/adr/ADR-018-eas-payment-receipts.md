# ADR-018: EAS payment receipts
**Status:** Accepted (chain round with anh Phúc, 2026-10-11) · Decision PH-11 · F-074

## Decision
After a request is Paid and reconciled, the core worker publishes an **EAS attestation** on Ethereum Sepolia with schema
`TreasuryPilot Payment Receipt v1 (bytes32 requestId, bytes32 invoiceHash, bytes32 approvalHash, bytes32 planHash, bytes32 payTxHash, address payee, uint256 amount, bytes32 policyVersion)`.
- Only hashes and addresses — no personal data or document content (BR-074).
- Attester: a dedicated **receipt key** in the core worker (not the executor, policy or sentinel key), with its own small ETH balance.
- Non-revocable; failures are retried and never affect the payment flow.
- The UI and evidence bundle link to easscan.

## Why
It lets anyone (judges, auditors, vendors) verify the chain *invoice → approval → attested plan → payment* without trusting our database.

## Consequences
SC-019 and REC-005 become P1 / Tier A. Schema UID is recorded in the deployments manifest.
