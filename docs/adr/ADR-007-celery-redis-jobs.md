# ADR-007: Celery + Redis for job execution, Postgres for truth
**Status:** Proposed · **Decision:** Q32 (lead's choice; BA had recommended a Postgres-only queue)

## Decision
- Celery 5 with a Redis broker. Celery beat handles the scheduler ticks (trigger, receipt polling, screening refresh, daily jobs).
- Task settings: `acks_late=True`, `task_reject_on_worker_lost=True`, idempotent tasks keyed by operation or plan id, bounded retries with backoff.
- **Per-treasury sequencing:** tasks acquire `pg_advisory_xact_lock(hash(treasury_id))` before planning or executing, and re-read state.
- **Truth:** tasks never carry state that is not in Postgres. A task payload is just ids.
- Flower runs for operations visibility (internal only).

## Alternatives
- A Postgres-only queue (SKIP LOCKED): fewer components.
- Dramatiq/RQ.

## Consequences
- Duplicate delivery is possible and is handled by idempotency and the advisory lock.
- Redis is not persisted for truth; losing it delays work but does not corrupt it.
