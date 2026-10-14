# Worker runtime

The worker package runs as three Compose services:

- `worker` consumes the `core` queue and is the only worker allowed to receive
  policy-attestation and signer credentials.
- `worker-ai` consumes the `ai` queue. Its environment is an explicit allowlist of the Redis
  URL, a least-privilege database URL and the LLM provider key. An unset `AI_DATABASE_URL`
  gives this process no database credential rather than falling back to the core database
  user; AI tasks then fail when they build the adapter, because every AI call must be
  written to `ai_calls` (AGT-002).
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

## Notification email delivery

The core worker sends immediate notifications once per minute and groups daily preferences at 08:00 UTC. Configure the worker with:

- `DATABASE_URL` for the notification tables.
- `TP_RESEND_API_KEY` and `TP_RESEND_FROM_EMAIL` for Resend delivery.
- `TP_SESSION_SECRET` (at least 32 bytes), matching the API secret, to sign unsubscribe links.
- `TP_APP_BASE_URL` for authenticated in-app links (default `http://localhost:5173`).
- `TP_PUBLIC_API_BASE_URL` for the API's one-click unsubscribe endpoint (default `http://localhost:8000`).

The user preference API is `GET`/`PUT /v1/me/notifications/email` with `delivery_mode` set to `immediate`, `daily`, or `off`. Users may also unsubscribe from an email using its List-Unsubscribe URL. The worker always sends `CRITICAL` security notifications through the immediate task, even when a user has selected `off`. Email content uses the in-app notification summary and link, without event payload details. Failed sends are retried; a crash after provider acceptance can duplicate a message after the 10-minute claim timeout.

Run the real lock-contention integration test against PostgreSQL with:

```bash
TEST_DATABASE_URL=postgresql://user:password@localhost:5432/treasurypilot \
  uv run pytest services/worker/tests/test_locks.py -m integration
```
