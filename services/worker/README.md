# Worker runtime

The worker package runs as three Compose services:

- `worker` consumes the `core` queue and is the only worker allowed to receive
  policy-attestation and signer credentials.
- `worker-ai` consumes the `ai` queue. Its environment is an explicit allowlist of the Redis
  URL, an optional least-privilege database URL and the LLM provider key. An unset
  `AI_DATABASE_URL` gives this process no database credential rather than falling back to the
  core database user.
- `beat` publishes periodic jobs. Business schedules are added by their owning tickets.

All tasks inherit `SafeTask`: late acknowledgement, rejection/redelivery when a worker process
is lost, bounded exponential retry for `RetryableTaskError`, and propagated
log context: the `x_correlation_id` header plus an `x_log_context` dict holding `correlation_id`,
`request_id`, `org_id`, `plan_id` and `operation_id`. A delivery binds them into structlog for its
lifetime and child tasks inherit them; set `TP_LOG_LEVEL` / `TP_LOG_FORMAT` to tune output. Redis dispatches work but does not own business state.

Use `make_idempotency_key(task_name, *durable_ids)` to derive an opaque, stable key, persist it
with the relevant Postgres state/outbox row, and re-read that state on every delivery. The helper
does not turn Redis into an idempotency store.

Treasury critical sections must use `treasury_advisory_xact_lock(pool, treasury_id)`. The context
yields `None` when the non-blocking Postgres lock is busy; otherwise it yields the connection that
owns the transaction and lock. All protected reads and writes must use that connection and must
finish before the context exits.

Run the real lock-contention integration test against PostgreSQL with:

```bash
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/treasurypilot \
  uv run pytest services/worker/tests/test_locks.py -m integration
```
