"""Circuit-breaker evaluation and auto-pause (RCV-006, BR-065, M12 §8.4).

Once per cycle (60 s) and per treasury: read the rule thresholds (default or Owner-tightened),
find trips, record one ``circuit_events`` row each, set the backend pause (same upsert as
POST /pause, ``onchain_status`` Requested until the indexer sees ``Paused``), notify, then ask the
signer's pause-only sentinel (ADR-017) to pause the module on-chain. A failed or missing sentinel
leaves the backend pause in force and the notified Guardian submits the Safe pause by hand.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import aiohttp
import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.circuit import COOLDOWN_SECONDS, SPECS, CircuitRule
from treasurypilot_worker.audit import append_audit
from treasurypilot_worker.locks import treasury_advisory_xact_lock

# Returns SENTINEL_SUBMITTED | ALREADY_PAUSED | SENTINEL_FAILED | NOT_CONFIGURED.
Sentinel = Callable[[uuid.UUID], Awaitable[str]]


@dataclass(frozen=True)
class Trip:
    rule: CircuitRule
    action: str  # ALERT | PAUSE
    dedupe_key: str
    details: dict[str, Any] = field(default_factory=dict)


async def _limits(
    conn: asyncpg.Connection, treasury_id: uuid.UUID
) -> dict[CircuitRule, tuple[int, int]]:
    limits = {rule: (spec.threshold, spec.window_seconds) for rule, spec in SPECS.items()}
    for row in await conn.fetch(
        "SELECT rule, threshold, window_seconds FROM circuit_rules WHERE treasury_id = $1",
        treasury_id,
    ):
        limits[CircuitRule(row["rule"])] = (row["threshold"], row["window_seconds"])
    return limits


async def _in_cooldown(conn: asyncpg.Connection, treasury_id: uuid.UUID, rule: CircuitRule) -> bool:
    return bool(
        await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM circuit_events WHERE treasury_id = $1 AND rule = $2 "
            "AND created_at > now() - make_interval(secs => $3))",
            treasury_id,
            rule.value,
            COOLDOWN_SECONDS,
        )
    )


async def _windowed(
    conn: asyncpg.Connection,
    treasury_id: uuid.UUID,
    rule: CircuitRule,
    count_sql: str,
    limits: tuple[int, int],
) -> Trip | None:
    threshold, window = limits
    count = await conn.fetchval(count_sql, treasury_id, window, rule.value)
    if count < threshold or await _in_cooldown(conn, treasury_id, rule):
        return None
    key = f"{rule.value}:{uuid.uuid4()}"
    return Trip(
        rule, "PAUSE", key, {"count": count, "threshold": threshold, "windowSeconds": window}
    )


async def _coverage_drop(
    conn: asyncpg.Connection, treasury_id: uuid.UUID, org_id: uuid.UUID
) -> Trip | None:
    """COMPLETE to anything else; the last coverage seen lives in the rule row's state."""
    now = await conn.fetchval("SELECT coverage::text FROM treasuries WHERE id = $1", treasury_id)
    spec = SPECS[CircuitRule.COVERAGE_DROP]
    previous = await conn.fetchval(
        "SELECT state ->> 'coverage' FROM circuit_rules "
        "WHERE treasury_id = $1 AND rule = 'COVERAGE_DROP'",
        treasury_id,
    )
    await conn.execute(
        "INSERT INTO circuit_rules (id, org_id, treasury_id, rule, threshold, window_seconds, state) "
        "VALUES ($1, $2, $3, 'COVERAGE_DROP', $4, $5, jsonb_build_object('coverage', $6::text)) "
        "ON CONFLICT (treasury_id, rule) DO UPDATE SET "
        "state = jsonb_build_object('coverage', $6::text)",
        uuid.uuid4(),
        org_id,
        treasury_id,
        spec.threshold,
        spec.window_seconds,
        now,
    )
    if (
        previous != "COMPLETE"
        or now == "COMPLETE"
        or await _in_cooldown(conn, treasury_id, CircuitRule.COVERAGE_DROP)
    ):
        return None
    return Trip(
        CircuitRule.COVERAGE_DROP,
        "PAUSE",
        f"COVERAGE_DROP:{uuid.uuid4()}",
        {"from": previous, "to": now},
    )


async def _outflow_pct_exceeded(
    conn: asyncpg.Connection,
    treasury_id: uuid.UUID,
    movement: asyncpg.Record,
    pct: int,
    signal_at: Any,
) -> tuple[bool, str | None]:
    """True when the movement is above ``pct`` % of the wallet's balance, or the balance is unknown."""
    snapshot = await conn.fetchrow(
        "SELECT data, block_timestamp FROM snapshots WHERE treasury_id = $1 "
        "ORDER BY block_number DESC LIMIT 1",
        treasury_id,
    )
    if snapshot is None:
        return True, None  # fail closed: the share cannot be shown to be small
    data = json.loads(snapshot["data"]) if isinstance(snapshot["data"], str) else snapshot["data"]
    wallet = "0x" + bytes(movement["wallet"]).hex()
    balance = next(
        (int(v) for k, v in (data.get("balances") or {}).items() if k.lower() == wallet), None
    )
    if balance is None:
        return True, None
    amount = int(movement["amount"])
    # A snapshot taken before the signal still holds the pre-outflow balance (shortcut: block time
    # vs signal time, no per-block balance). Otherwise add the amount back.
    before = balance if snapshot["block_timestamp"] < signal_at else balance + amount
    return before == 0 or amount * 100 > pct * before, str(before)


async def _signals(conn: asyncpg.Connection, treasury_id: uuid.UUID, pct: int) -> list[Trip]:
    trips = []
    for s in await conn.fetch(
        "SELECT s.id, s.token_movement_id, s.verification_id, s.created_at FROM chain_safety_signals s "
        "WHERE s.treasury_id = $1 AND s.signal_type = 'CIRCUIT_BREAKER' AND s.consumed_at IS NULL "
        "AND s.invalidated_at IS NULL AND NOT EXISTS (SELECT 1 FROM circuit_events e "
        "WHERE e.treasury_id = s.treasury_id AND e.dedupe_key = 'signal:' || s.id::text) "
        "ORDER BY s.created_at",
        treasury_id,
    ):
        key = f"signal:{s['id']}"
        if s["verification_id"] is not None:
            trips.append(
                Trip(
                    CircuitRule.DISCREPANCY,
                    "PAUSE",
                    key,
                    {"verificationId": str(s["verification_id"])},
                )
            )
            continue
        movement = await conn.fetchrow(
            "SELECT wallet, amount FROM token_movements WHERE id = $1 AND NOT removed",
            s["token_movement_id"],
        )
        if movement is None:
            continue
        over, before = await _outflow_pct_exceeded(
            conn, treasury_id, movement, pct, s["created_at"]
        )
        trips.append(
            Trip(
                CircuitRule.UNEXPECTED_OUTFLOW,
                "PAUSE" if over else "ALERT",
                key,
                {
                    "tokenMovementId": str(s["token_movement_id"]),
                    "amount": str(movement["amount"]),
                    "balanceBefore": before,
                    "thresholdPercent": pct,
                },
            )
        )
    return trips


# Only rows newer than the rule's last trip count, so a spent rejection cannot re-trip the rule
# once the cool-down ends. Distinct steps/requests: a retried step is one rejection.
_AFTER_LAST_TRIP = (
    "COALESCE((SELECT max(created_at) FROM circuit_events "
    "WHERE treasury_id = $1 AND rule = $3), '-infinity')"
)
# Timing is the revert's confirmation time when a transaction carries one; simulation reverts have
# no transaction, so they use the operation's created_at (shortcut: the attempt time, not the
# revert time; fine while operations are rejected within seconds of creation).
_REJECTED_AT = (
    "COALESCE((SELECT max(t.confirmed_at) FROM transactions t "
    "WHERE t.operation_id = o.id AND t.status = 'Reverted'), o.created_at)"
)
_REJECTIONS_SQL = (
    "SELECT count(DISTINCT o.plan_step_id) FROM operations o WHERE o.treasury_id = $1 "
    f"AND {_REJECTED_AT} > now() - make_interval(secs => $2) "
    f"AND {_REJECTED_AT} > {_AFTER_LAST_TRIP} "
    "AND (o.status = 'Reverted' OR o.last_error LIKE 'SIMULATION_REVERTED%')"
)
_AI_REJECTED_SQL = (
    "SELECT count(DISTINCT request_id) FROM review_items WHERE treasury_id = $1 "
    "AND type = 'AI_REJECTED' AND created_at > now() - make_interval(secs => $2) "
    f"AND created_at > {_AFTER_LAST_TRIP}"
)


async def _find_trips(
    conn: asyncpg.Connection, treasury_id: uuid.UUID, org_id: uuid.UUID
) -> list[Trip]:
    limits = await _limits(conn, treasury_id)
    found = [
        await _windowed(
            conn,
            treasury_id,
            CircuitRule.REJECTIONS,
            _REJECTIONS_SQL,
            limits[CircuitRule.REJECTIONS],
        ),
        await _windowed(
            conn,
            treasury_id,
            CircuitRule.AI_PLAN_REJECTED,
            _AI_REJECTED_SQL,
            limits[CircuitRule.AI_PLAN_REJECTED],
        ),
        await _coverage_drop(conn, treasury_id, org_id),
    ]
    return [t for t in found if t is not None] + await _signals(
        conn, treasury_id, limits[CircuitRule.UNEXPECTED_OUTFLOW][0]
    )


# Keep in sync with mandate/pause.py _upsert_pause (the API's SQLAlchemy twin of this upsert).
# The system acts here, so created_by/updated_by stay NULL (nullable, ON DELETE SET NULL).
_PAUSE = """
INSERT INTO backend_pause (treasury_id, org_id, paused, reason, onchain_status)
VALUES ($1, $2, true, $3, 'Requested')
ON CONFLICT (treasury_id) DO UPDATE SET
    reason = CASE WHEN backend_pause.paused THEN backend_pause.reason ELSE EXCLUDED.reason END,
    paused = true,
    onchain_status = CASE WHEN backend_pause.onchain_status = 'NotRequested'
                          THEN 'Requested' ELSE backend_pause.onchain_status END,
    updated_by = NULL, updated_at = now(), version = backend_pause.version + 1
"""


async def _record(
    conn: asyncpg.Connection, treasury_id: uuid.UUID, org_id: uuid.UUID, trip: Trip
) -> uuid.UUID | None:
    event_id = uuid.uuid4()
    inserted = await conn.fetchval(
        "INSERT INTO circuit_events (id, org_id, treasury_id, rule, action, dedupe_key, details) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb) ON CONFLICT (treasury_id, dedupe_key) DO NOTHING "
        "RETURNING id",
        event_id,
        org_id,
        treasury_id,
        trip.rule.value,
        trip.action,
        trip.dedupe_key,
        json.dumps(trip.details),
    )
    if inserted is None:
        return None
    if trip.action == "PAUSE":
        await conn.execute(_PAUSE, treasury_id, org_id, f"Circuit breaker: {trip.rule.value}")
        # Signal rules record every signal, but notify once per cool-down (also within one cycle:
        # now() is the transaction start, so same-cycle events count as recent).
        notify = not await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM circuit_events WHERE treasury_id = $1 AND rule = $2 "
            "AND action = 'PAUSE' AND id <> $4 AND created_at > now() - make_interval(secs => $3))",
            treasury_id,
            trip.rule.value,
            COOLDOWN_SECONDS,
            event_id,
        )
        # An ALERT outflow is already notified by the indexer (UnexpectedOutflow).
        if notify:
            await _notify(conn, treasury_id, org_id, trip, event_id)
    await append_audit(
        conn,
        org_id,
        action="treasury.circuit_breaker_tripped",
        entity_type="treasury",
        entity_id=str(treasury_id),
        data={"rule": trip.rule.value, "action": trip.action, **trip.details},
    )
    return event_id


async def _notify(
    conn: asyncpg.Connection,
    treasury_id: uuid.UUID,
    org_id: uuid.UUID,
    trip: Trip,
    event_id: uuid.UUID,
) -> None:
    await conn.execute(
        "INSERT INTO domain_events (id, org_id, treasury_id, type, entity_type, entity_id, payload) "
        "VALUES ($1, $2, $3, 'CircuitBreakerTripped', 'treasury', $3, $4::jsonb)",
        uuid.uuid4(),
        org_id,
        treasury_id,
        json.dumps({"rule": trip.rule.value, "circuitEventId": str(event_id)}),
    )


async def evaluate_circuit_breakers(pool: asyncpg.Pool, sentinel: Sentinel) -> int:
    """Evaluate every Ready or Paused treasury; return the number of PAUSE trips."""
    paused = 0
    for t in await pool.fetch(
        "SELECT id, org_id FROM treasuries WHERE status::text IN ('Ready', 'Paused')"
    ):
        pending: list[uuid.UUID] = []
        async with treasury_advisory_xact_lock(pool, t["id"]) as conn:
            if conn is None:
                continue  # another worker is on it; next cycle
            for trip in await _find_trips(conn, t["id"], t["org_id"]):
                event_id = await _record(conn, t["id"], t["org_id"], trip)
                if event_id is not None and trip.action == "PAUSE":
                    pending.append(event_id)
        paused += len(pending)
        # Retry an on-chain pause that never landed (sentinel down or unconfigured): the signer is
        # idempotent (alreadyPaused). Only the latest PAUSE event of a still-Requested pause.
        retry = await pool.fetchval(
            "SELECT e.id FROM circuit_events e JOIN backend_pause b ON b.treasury_id = e.treasury_id "
            "WHERE e.treasury_id = $1 AND e.action = 'PAUSE' AND b.paused "
            "AND b.onchain_status = 'Requested' "
            "AND COALESCE(e.details ->> 'onchain', 'NOT_CONFIGURED') "
            "IN ('NOT_CONFIGURED', 'SENTINEL_FAILED') "
            "AND e.created_at = (SELECT max(created_at) FROM circuit_events "
            "WHERE treasury_id = $1 AND action = 'PAUSE') LIMIT 1",
            t["id"],
        )
        if retry is not None and retry not in pending:
            pending.append(retry)
        if pending:
            # Outside the transaction: the backend pause is committed and holds regardless.
            onchain = await sentinel(t["id"])
            await pool.execute(
                "UPDATE circuit_events SET details = details || jsonb_build_object('onchain', $2::text) "
                "WHERE id = ANY($1::uuid[])",
                pending,
                onchain,
            )
    return paused


def http_sentinel(signer_url: str | None, secret: str | None) -> Sentinel:
    async def call(treasury_id: uuid.UUID) -> str:
        if not signer_url or not secret:
            return "NOT_CONFIGURED"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as http:
                async with http.post(
                    signer_url.rstrip("/") + "/sentinel/pause",
                    json={"treasuryId": str(treasury_id)},
                    headers={"X-Signer-Secret": secret},
                    allow_redirects=False,  # the secret header must never follow a redirect
                ) as response:
                    if response.status != 200:
                        return "SENTINEL_FAILED"
                    body = await response.json()
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return "SENTINEL_FAILED"
        return "ALREADY_PAUSED" if body.get("alreadyPaused") else "SENTINEL_SUBMITTED"

    return call
