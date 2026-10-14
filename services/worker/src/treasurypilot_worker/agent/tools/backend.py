"""Read-only data access for the agent tools. Every method is scoped to one organisation."""

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]

DB_TIMEOUT_S = 5.0
MAX_REQUESTS = 100
MAX_PAYEES = 100
# Requests a planner may still act on: not a draft, not finished, not terminal.
OPEN_STATUSES = (
    "AwaitingApproval",
    "Approved",
    "Scheduled",
    "Planning",
    "AwaitingAuthority",
    "Preparing",
    "Paying",
    "NeedsReview",
)


@dataclass(frozen=True)
class SnapshotRow:
    id: UUID
    treasury_id: UUID
    purpose: str
    block_number: int
    block_hash: str
    block_timestamp: datetime
    coverage: str
    missing: tuple[str, ...]
    data: dict[str, Any]


@dataclass(frozen=True)
class RequestRow:
    id: UUID
    invoice_no: str | None
    vendor_name: str | None
    amount: int | None
    due_at: date
    status: str
    terms: dict[str, Any] | None  # only when an owner confirmed them
    flags: tuple[str, ...]


@dataclass(frozen=True)
class PayeeRow:
    id: UUID
    label: str
    address: str
    status: str


@dataclass(frozen=True)
class PolicyRow:
    mandate_version: int
    config: dict[str, Any]
    payees: tuple[PayeeRow, ...]


class ToolBackend(Protocol):
    """Everything the tools may read. There is no write method, by design."""

    def treasury_in_org(self, org_id: UUID, treasury_id: UUID) -> bool: ...

    def latest_complete_snapshot(self, org_id: UUID, treasury_id: UUID) -> SnapshotRow | None: ...

    def snapshot_by_id(self, org_id: UUID, snapshot_id: UUID) -> SnapshotRow | None: ...

    def list_requests(
        self, org_id: UUID, treasury_id: UUID, statuses: Sequence[str]
    ) -> list[RequestRow]:
        """At most `MAX_REQUESTS + 1` rows, so the caller can tell the list was cut."""
        ...

    def active_policy(self, org_id: UUID, treasury_id: UUID) -> PolicyRow | None: ...


_SNAPSHOT = """
SELECT id, treasury_id, purpose, block_number, block_hash, block_timestamp, coverage,
       missing, data
FROM snapshots
"""
_REQUESTS = f"""
SELECT r.id, r.invoice_no, v.name AS vendor_name, r.amount, r.due_at, r.status::text AS status,
       CASE WHEN r.terms_confirmed_at IS NOT NULL THEN r.terms END AS terms,
       COALESCE((SELECT array_agg(f.code ORDER BY f.code) FROM flags AS f
                 WHERE f.request_id = r.id AND f.revision = r.current_revision
                   AND f.status = 'Open'), '{{}}') AS flags
FROM payment_requests AS r
LEFT JOIN vendors AS v ON v.id = r.vendor_id
WHERE r.org_id = $1 AND r.treasury_id = $2 AND r.status::text = ANY($3::text[])
ORDER BY r.due_at, r.id
LIMIT {MAX_REQUESTS + 1}
"""


def _json(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


def _snapshot(row: asyncpg.Record) -> SnapshotRow:
    return SnapshotRow(
        id=row["id"],
        treasury_id=row["treasury_id"],
        purpose=row["purpose"],
        block_number=row["block_number"],
        block_hash="0x" + bytes(row["block_hash"]).hex(),
        block_timestamp=row["block_timestamp"],
        coverage=row["coverage"],
        missing=tuple(_json(row["missing"])),
        data=_json(row["data"]),
    )


class PostgresToolBackend:
    """Reads through `READ ONLY` transactions: the database refuses any write (acceptance)."""

    def __init__(self, database_url: str) -> None:
        # Compose hands out the SQLAlchemy form of the URL.
        self._dsn = database_url.replace("postgresql+asyncpg://", "postgresql://", 1)

    def treasury_in_org(self, org_id: UUID, treasury_id: UUID) -> bool:
        async def read(connection: asyncpg.Connection) -> bool:
            return bool(
                await connection.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM treasuries WHERE id = $1 AND org_id = $2)",
                    treasury_id,
                    org_id,
                )
            )

        return self._run(read)

    def latest_complete_snapshot(self, org_id: UUID, treasury_id: UUID) -> SnapshotRow | None:
        return self._snapshot(
            "WHERE org_id = $1 AND treasury_id = $2 AND coverage = 'COMPLETE' "
            "ORDER BY block_number DESC LIMIT 1",
            org_id,
            treasury_id,
        )

    def snapshot_by_id(self, org_id: UUID, snapshot_id: UUID) -> SnapshotRow | None:
        return self._snapshot("WHERE org_id = $1 AND id = $2", org_id, snapshot_id)

    def list_requests(
        self, org_id: UUID, treasury_id: UUID, statuses: Sequence[str]
    ) -> list[RequestRow]:
        async def read(connection: asyncpg.Connection) -> list[RequestRow]:
            rows = await connection.fetch(_REQUESTS, org_id, treasury_id, list(statuses))
            return [
                RequestRow(
                    id=row["id"],
                    invoice_no=row["invoice_no"],
                    vendor_name=row["vendor_name"],
                    amount=None if row["amount"] is None else int(row["amount"]),
                    due_at=row["due_at"],
                    status=row["status"],
                    terms=_json(row["terms"]),
                    flags=tuple(row["flags"]),
                )
                for row in rows
            ]

        return self._run(read)

    def active_policy(self, org_id: UUID, treasury_id: UUID) -> PolicyRow | None:
        async def read(connection: asyncpg.Connection) -> PolicyRow | None:
            mandate = await connection.fetchrow(
                "SELECT version, config FROM mandate_versions "
                "WHERE org_id = $1 AND treasury_id = $2 AND status = 'Active'",
                org_id,
                treasury_id,
            )
            if mandate is None:
                return None
            payees = await connection.fetch(
                "SELECT id, label, address, status::text AS status FROM payees "
                f"WHERE org_id = $1 AND treasury_id = $2 ORDER BY label, id LIMIT {MAX_PAYEES}",
                org_id,
                treasury_id,
            )
            return PolicyRow(
                mandate_version=mandate["version"],
                config=_json(mandate["config"]),
                payees=tuple(
                    PayeeRow(p["id"], p["label"], "0x" + bytes(p["address"]).hex(), p["status"])
                    for p in payees
                ),
            )

        return self._run(read)

    def _snapshot(self, where: str, *args: Any) -> SnapshotRow | None:
        async def read(connection: asyncpg.Connection) -> SnapshotRow | None:
            row = await connection.fetchrow(f"{_SNAPSHOT} {where}", *args)
            return None if row is None else _snapshot(row)

        return self._run(read)

    def _run[T](self, read: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        # shortcut: one connection per tool call (calls take seconds), run with `asyncio.run`
        # like `PostgresAiCallLog`, so sync Celery tasks only; pool it if that changes.
        return asyncio.run(self._execute(read))

    async def _execute[T](self, read: Callable[[asyncpg.Connection], Awaitable[T]]) -> T:
        connection = await asyncpg.connect(
            self._dsn, timeout=DB_TIMEOUT_S, command_timeout=DB_TIMEOUT_S
        )
        try:
            # The single door to the database: nothing here can write.
            async with connection.transaction(readonly=True):
                return await read(connection)
        finally:
            await connection.close()
