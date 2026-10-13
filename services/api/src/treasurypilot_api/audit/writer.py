from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
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


def _json_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("audit timestamps must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("audit data cannot contain a non-finite decimal")
        return format(value, "f")
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("audit data object keys must be strings")
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("audit data cannot contain NaN or infinity")
    if value is None or isinstance(value, str | int | float | bool):
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

    Monetary values in ``data`` should be supplied as integer base-unit strings.
    Decimal values are normalized to strings. Hashes are stored as raw SHA-256 bytes;
    canonical records encode them as lowercase hexadecimal strings.
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

    # Upsert first so concurrent first writes for an org serialize on the unique org_id.
    await session.execute(
        insert(AuditHead)
        .values(org_id=org_id, last_seq=None, last_hash=ZERO_HASH)
        .on_conflict_do_nothing(index_elements=[AuditHead.org_id])
    )
    head = await session.scalar(
        select(AuditHead).where(AuditHead.org_id == org_id).with_for_update()
    )
    if head is None:
        raise RuntimeError("failed to create or lock audit head")

    previous_hash = head.last_hash
    at = datetime.now(UTC)
    seq = await session.scalar(text("SELECT nextval(pg_get_serial_sequence('audit_log', 'seq'))"))
    if not isinstance(seq, int):
        raise RuntimeError("failed to allocate audit sequence")

    record = {
        "seq": seq,
        "org_id": str(org_id),
        "at": at,
        "actor_type": actor_type,
        "actor_id": str(actor.actor_id) if actor.actor_id is not None else None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": str(entity.entity_id) if entity.entity_id is not None else None,
        "data": normalized_data,
        "prev_hash": previous_hash.hex(),
    }
    record_hash = hashlib.sha256(previous_hash + _canonical_json(record)).digest()

    audit_row = AuditLog(
        seq=seq,
        org_id=org_id,
        at=at,
        actor_type=actor_type,
        actor_id=record["actor_id"],
        action=action,
        entity_type=entity_type,
        entity_id=record["entity_id"],
        data=normalized_data,
        prev_hash=previous_hash,
        hash=record_hash,
    )
    session.add(audit_row)
    head.last_seq = seq
    head.last_hash = record_hash
    # Surface persistence/constraint failures before the caller proceeds to commit.
    await session.flush()
    return audit_row
