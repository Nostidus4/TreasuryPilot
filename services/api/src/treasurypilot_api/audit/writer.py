from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.audit.models import AuditActorType, AuditHead, AuditLog

ZERO_HASH = bytes(32)


@dataclass(frozen=True, slots=True)
class AuditActor:
    actor_type: AuditActorType
    actor_id: str | uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AuditEntity:
    entity_type: str
    entity_id: str | uuid.UUID | None = None


class AuditHeadMissing(RuntimeError):
    """The organization has no audit head; a new chain is never started silently."""


def _text(value: str) -> str:
    # Postgres JSONB rejects U+0000; fail here instead of aborting the caller's transaction.
    if "\x00" in value:
        raise ValueError("audit data cannot contain NUL characters")
    return value


def _json_value(value: Any) -> Any:
    """Normalize ``value`` to JSON that survives the JSONB round trip unchanged.

    Hashes are recomputed from stored rows, so every value must read back exactly as
    it was hashed: floats are rejected (JSONB renormalizes them) and Decimals must be
    integral (amounts are integer base units) and are written as plain digit strings.
    """

    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("audit timestamps must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite() or value != value.to_integral_value():
            raise ValueError("audit decimals must be integral base units")
        return str(int(value))
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("audit data object keys must be strings")
        return {_text(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, float):
        raise TypeError("audit data cannot contain floats; pass amounts as strings")
    if isinstance(value, str):
        return _text(value)
    if value is None or isinstance(value, int | bool):
        return value
    raise TypeError(f"unsupported audit data value: {type(value).__name__}")


def _canonical_json(value: Mapping[str, object]) -> bytes:
    normalized = _json_value(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def compute_hash(row: AuditLog) -> bytes:
    """Return the chain hash of ``row``; verifiers recompute it from stored rows."""

    record = {
        "seq": row.seq,
        "org_id": str(row.org_id),
        "at": row.at,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "data": row.data,
        "prev_hash": row.prev_hash.hex(),
    }
    return hashlib.sha256(_canonical_json(record)).digest()


async def write(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    actor: AuditActor,
    action: str,
    entity: AuditEntity,
    data: Mapping[str, object],
) -> AuditLog:
    """Append one record using the caller's transaction; this function never commits.

    ``hash = sha256(canonical_json(record))``, where the record includes ``prev_hash``
    as lowercase hex; hashes are stored as raw SHA-256 bytes. Monetary values in
    ``data`` are integer base-unit strings (integral Decimals are converted).

    This locks the org's audit head until the caller commits, so call it as the last
    step before commit, and when one transaction audits several orgs, write them in
    ascending ``org_id`` order to avoid deadlocks.
    """

    try:
        actor_type = AuditActorType(actor.actor_type).value
    except ValueError as exc:
        raise ValueError(f"unsupported audit actor type: {actor.actor_type}") from exc
    action = action.strip()
    entity_type = entity.entity_type.strip()
    if not action:
        raise ValueError("audit action must not be empty")
    if not entity_type:
        raise ValueError("audit entity type must not be empty")
    if not isinstance(data, Mapping):
        raise TypeError("audit data must be a mapping")

    normalized_data = _json_value(data)
    if not isinstance(normalized_data, dict):
        raise TypeError("audit data must be an object")

    # The head is created with the organization (DB trigger). One statement locks it and
    # allocates the sequence. populate_existing re-reads a head already in the session's
    # identity map, so a reused session can never chain onto a stale hash.
    row = (
        await session.execute(
            select(AuditHead, func.nextval(func.pg_get_serial_sequence("audit_log", "seq")))
            .where(AuditHead.org_id == org_id)
            .with_for_update(of=AuditHead)
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if row is None:
        raise AuditHeadMissing(f"organization {org_id} has no audit head")
    head = cast(AuditHead, row[0])
    seq = cast(int, row[1])

    previous_hash = head.last_hash
    at = datetime.now(UTC)

    audit_row = AuditLog(
        seq=seq,
        org_id=org_id,
        at=at,
        actor_type=actor_type,
        actor_id=str(actor.actor_id) if actor.actor_id is not None else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity.entity_id) if entity.entity_id is not None else None,
        data=normalized_data,
        prev_hash=previous_hash,
    )
    audit_row.hash = compute_hash(audit_row)
    session.add(audit_row)
    head.last_seq = seq
    head.last_hash = audit_row.hash
    # Surface persistence/constraint failures before the caller proceeds to commit.
    await session.flush()
    return audit_row
