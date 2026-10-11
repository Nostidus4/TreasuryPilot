# ADR-016: Per-request plan attestation (EIP-712) and pre-submit simulation
**Status:** Accepted (M08 grilling, 2026-10-11) · **Decisions:** M08-D1 … M08-D5

## Context
The signer must sign only steps the validator allowed (BR-059). The contract is the final authority, but the Python validator mirrors its checks and can drift. Execution is one request at a time (BR-050) and state is re-read before every step (BR-051).

## Decision
- The validated and attested unit is **one request's execution plan** (optional REFILL, then PAY).
- The core worker signs a `PlanAttestation` (EIP-712, domain "TreasuryPilot Policy", bound to chainId and the module clone) with a dedicated secp256k1 **policy key**, valid 15 minutes, random nonce.
- Before each step: fresh snapshot → validator (PRE_STEP) → `eth_call` simulation from the executor address (SIMULATION). Any non-ALLOW stops the chain without undoing completed steps.
- The signer verifies the attestation, recomputes planHash, checks payload equality and nonce use (in its own `signer` schema), simulates again, then signs.

## Alternatives
- One attestation per day batch: larger blast radius, one blocked request stalls the rest.
- HMAC between worker and signer: simpler, but not verifiable by third parties or on-chain later.
- Validator only (no simulation): drift would surface as on-chain reverts and wasted gas.

## Consequences
- One more key to manage (keystore + rotation with two trusted addresses).
- One extra RPC call per step (free).
- On-chain verification of attestations can be added later (SC-L04) without changing the format.
