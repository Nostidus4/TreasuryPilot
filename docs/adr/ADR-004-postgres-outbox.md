# ADR-004: PostgreSQL as system of record + transactional outbox
**Status:** Accepted (G2, 2026-10-11) · **Rules:** BR-060, BR-061, BR-097 · **NFR:** REL-02/03

## Decision
- PostgreSQL 16 is the single source of off-chain truth.
- Every money-moving step is inserted into `operations` (status `NotSubmitted`, with fixed request and step ids) **in the same transaction** as the plan state change, before any signing.
- After signing, the `txHash` and `nonce` are persisted before broadcast.
- Audit records are written in the same transaction as the state they describe.

## Alternatives
- Using queue state as truth: loses information on broker failure.
- An event-sourcing database: heavier than needed.

## Consequences
- Recovery (F-080) works on Postgres + chain only. Redis loss is harmless.
