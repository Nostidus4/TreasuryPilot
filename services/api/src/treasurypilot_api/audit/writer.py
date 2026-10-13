from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from treasurypilot_api.audit.chain import _json_value, compute_hash
from treasurypilot_api.audit.models import AuditActorType, AuditHead, AuditLog


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
