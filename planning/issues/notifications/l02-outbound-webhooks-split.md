# NTF-L02 implementation split and estimate

NTF-L02 is marked Later and must be split before scheduling. The current issue combines endpoint lifecycle, secure delivery, retry policy, operations, and production integration under a single M estimate. Proposed child tickets:

| Proposed ticket | Scope | Estimate | Exit criteria |
|---|---|---:|---|
| NTF-L02a · Webhook endpoint lifecycle | Org-admin create/list/disable endpoints, URL validation, one-time secret display and encrypted storage, event-type filters | M | Tenant isolation, permission tests, secret never returned after creation |
| NTF-L02b · Signed delivery and retry | Outbox fanout, canonical JSON envelope, HMAC-SHA256 signing, bounded retry/backoff, delivery idempotency | M | Signature verification example and worker integration tests; endpoint failures never block in-app notifications |
| NTF-L02c · Dead-letter operations and replay | Inspect failed deliveries, replay authorization, audit trail, replay idempotency and retention | S | Only dead deliveries replay; retries reset safely; audit records identify actor and delivery |
| NTF-L02d · Deployment and operations | Secrets/configuration, metrics, SSRF-safe egress policy, runbook and integration environment | S | CI and deployment config cover sender; operational runbook and alert thresholds documented |

These are proposed planning units, not scheduled tickets. Implementation of NTF-L02 must not be declared ready until the project owner accepts this breakdown, endpoint provisioning and secret-storage decisions are finalized, and a PostgreSQL-backed integration environment verifies delivery and replay end to end.
