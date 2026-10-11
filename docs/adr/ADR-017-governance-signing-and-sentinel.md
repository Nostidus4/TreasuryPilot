# ADR-017: In-app Safe signature collection and a pause-only guardian sentinel
**Status:** Accepted (M03 grilling, 2026-10-11) · Decisions M03-D1, M03-D2, PH-4

## Context
Every governance change is a Safe T transaction, often 2-of-3. On-chain pause must be fast when the circuit breaker fires at night, but the agent must never hold spending or governance power beyond its mandate.

## Decision
1. **Signature collection in the app.** The API builds the SafeTx (MultiSend for bundles), owners sign its EIP-712 hash with their wallets in TreasuryPilot, the API verifies each signature against the Safe's on-chain owners, and the last owner executes `execTransaction` from their own wallet. Proposing to the Safe Transaction Service ("open in Safe{Wallet}") is optional. Works on any chain, including Anvil.
2. **Guardian Safe + sentinel.** `mandate.guardian` is a Safe with threshold 1 whose owners are the human guardian(s) and a **sentinel** key. The sentinel key lives in `signer` (encrypted keystore, separate from the executor key) behind one endpoint that can only produce `GuardianSafe.execTransaction(module, 0, pause())` for a configured treasury.

## Alternatives
- Safe Transaction Service only: external dependency, not on Anvil.
- Executor relays governance transactions: widens the signer's attack surface.
- No sentinel: on-chain pause waits for a human (minutes to hours).
- Executor key may pause: mixes spend and stop powers in one key (AP-3).

## Consequences
- New tables `governance_txs`, `governance_signatures`, `guardian_setups`.
- Sentinel leak = denial of service only (pause); the Owner resumes and removes the sentinel from the Guardian Safe.
- The sentinel needs its own small ETH balance and low-gas alert.
