# ADR-006: Signer service and executor key management
**Status:** Proposed · **Decision:** Q28 · **Rules:** BR-092 · **NFR:** SEC-03

## Decision
`services/signer` is a minimal internal FastAPI service with one endpoint, `POST /sign-and-send`. It:
1. verifies the `PlanAttestation` signature, expiry and nonce;
2. checks that the payload matches the attested step (function selector, args);
3. checks the chainId allowlist;
4. simulates the call;
5. signs with the executor key and broadcasts;
6. returns the txHash.

M1 key storage is an encrypted JSON keystore mounted read-only, with the password from a Docker secret. Prod uses a KMS adapter (AWS/GCP).

The signer has no DB write access. The worker records outcomes.

## Alternatives
- Key in the worker: next to LLM-calling code.
- MPC/TEE vendors: a third-party dependency on the scored security path.

## Consequences
- Known risk (documented): a compromised signer host can sign anything within the mandate. Bounded by the contract limits (blast radius, PROJECT_OVERVIEW §6).
