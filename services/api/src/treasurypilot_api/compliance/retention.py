"""Run bounded retention batches against invitations and authentication artifacts.

The policy row is locked before checking a hold or deleting records. Writers use an
upsert on the same row, so placing a hold and a deletion cannot pass each other.
Callers own the transaction for policy changes; the runner owns its transactions.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, delete, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditHead, AuditLog
from treasurypilot_api.compliance.models import (
    AuthRetentionPolicy,
    DeletionReceipt,
    RetentionPolicy,
)
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.models import Invite, MagicLink
from treasurypilot_api.identity.models import Session as AuthSession

logger = logging.getLogger(__name__)

# 100 years. Also enforced by a database check so ``now - timedelta`` cannot overflow.
MAX_INVITE_RETENTION_DAYS = 36500
MAX_AUTH_RETENTION_DAYS = 36500


def invite_receipt_hash(record_id: uuid.UUID) -> bytes:
    """Hash a random UUID, never an email, token or other personal field."""

    return hashlib.sha256(b"treasurypilot:invite:v1:" + record_id.bytes).digest()


def auth_receipt_hash(record_type: str, record_id: uuid.UUID) -> bytes:
    """Hash a random auth-row UUID with a domain-specific prefix."""

    if record_type not in {"session", "magic_link"}:
        raise ValueError("record_type must be 'session' or 'magic_link'")
    return hashlib.sha256(f"treasurypilot:{record_type}:v1:".encode() + record_id.bytes).digest()


async def configure_policy(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    invite_retention_days: int | None,
    legal_hold: bool,
) -> None:
    """Set the policy atomically. ``None`` disables scheduled invite deletion."""

    if invite_retention_days is not None and not (
        0 <= invite_retention_days <= MAX_INVITE_RETENTION_DAYS
    ):
        raise ValueError(f"invite_retention_days must be between 0 and {MAX_INVITE_RETENTION_DAYS}")
    statement = pg_insert(RetentionPolicy).values(
        org_id=org_id,
        invite_retention_days=invite_retention_days,
        legal_hold=legal_hold,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[RetentionPolicy.org_id],
            set_={
                "invite_retention_days": statement.excluded.invite_retention_days,
                "legal_hold": statement.excluded.legal_hold,
                "updated_at": datetime.now(UTC),
            },
        )
    )


async def configure_auth_policy(
    session: AsyncSession,
    *,
    session_retention_days: int | None,
    magic_link_retention_days: int | None,
    legal_hold: bool,
) -> None:
    """Set explicit deployment-wide auth retention; ``None`` disables a record type."""

    for name, days in (
        ("session_retention_days", session_retention_days),
        ("magic_link_retention_days", magic_link_retention_days),
    ):
        if days is not None and not 0 <= days <= MAX_AUTH_RETENTION_DAYS:
            raise ValueError(f"{name} must be between 0 and {MAX_AUTH_RETENTION_DAYS}")
    statement = pg_insert(AuthRetentionPolicy).values(
        id=1,
        session_retention_days=session_retention_days,
        magic_link_retention_days=magic_link_retention_days,
        legal_hold=legal_hold,
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[AuthRetentionPolicy.id],
            set_={
                "session_retention_days": statement.excluded.session_retention_days,
                "magic_link_retention_days": statement.excluded.magic_link_retention_days,
                "legal_hold": statement.excluded.legal_hold,
                "updated_at": datetime.now(UTC),
            },
        )
    )


@dataclass(frozen=True, slots=True)
class RetentionResult:
    examined: int
    deleted: int
    failed: int = 0


async def run_retention(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    batch_size: int = 100,
    dry_run: bool = True,
) -> RetentionResult:
    """Process at most one bounded batch per organization, oldest first.

    Each organization has a separate transaction. Any failure rolls back both the
    deletion and its receipt and is logged without stopping the remaining organizations;
    a retry is safe and does not duplicate receipts. A dry run takes no write locks.

    Before deleting, the organization's audit head is locked. Every audit writer holds
    that lock until it commits, so no audit entry naming a candidate invite can commit
    between the reference check and the deletion.
    """

    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")

    examined = deleted = failed = 0
    async with sessions() as session:
        org_ids = list(
            await session.scalars(
                select(RetentionPolicy.org_id)
                .where(
                    RetentionPolicy.legal_hold.is_(False),
                    RetentionPolicy.invite_retention_days.is_not(None),
                )
                .order_by(RetentionPolicy.org_id)
            )
        )

    for org_id in org_ids:
        try:
            org_examined, org_deleted = await _run_org(
                sessions, org_id, now=now, batch_size=batch_size, dry_run=dry_run
            )
        except Exception:
            logger.exception("invite retention failed for organization %s", org_id)
            failed += 1
            continue
        examined += org_examined
        deleted += org_deleted

    try:
        auth_examined, auth_deleted = await _run_auth(
            sessions, now=now, batch_size=batch_size, dry_run=dry_run
        )
    except Exception:
        logger.exception("authentication retention failed")
        failed += 1
    else:
        examined += auth_examined
        deleted += auth_deleted

    return RetentionResult(examined=examined, deleted=deleted, failed=failed)


async def _run_org(
    sessions: async_sessionmaker[AsyncSession],
    org_id: uuid.UUID,
    *,
    now: datetime,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    async with sessions() as session, session.begin():
        # A preview must not block legal-hold changes, so it reads without locking.
        policy = await session.get(RetentionPolicy, org_id, with_for_update=not dry_run)
        if policy is None or policy.legal_hold or policy.invite_retention_days is None:
            return 0, 0
        if not dry_run:
            # Same order as audit writers that also change policy: policy, then head.
            await session.execute(
                select(AuditHead.org_id).where(AuditHead.org_id == org_id).with_for_update()
            )
        cutoff = now - timedelta(days=policy.invite_retention_days)
        email = func.lower(cast(Invite.email, String))
        query = (
            select(Invite.id)
            .where(
                Invite.org_id == org_id,
                Invite.expires_at <= cutoff,
                # The hash chain is immutable. Keep the source record when an audit
                # entry still names its id or email (emails compare case-insensitively).
                ~exists(
                    select(AuditLog.seq).where(
                        AuditLog.org_id == Invite.org_id,
                        or_(
                            AuditLog.entity_id == cast(Invite.id, String),
                            func.lower(AuditLog.entity_id) == email,
                            func.lower(AuditLog.actor_id) == email,
                            func.strpos(func.lower(cast(AuditLog.data, String)), email) > 0,
                        ),
                    )
                ),
            )
            .order_by(Invite.expires_at, Invite.id)
            .limit(batch_size)
        )
        if not dry_run:
            query = query.with_for_update(skip_locked=True)
        record_ids = list(await session.scalars(query))
        if dry_run or not record_ids:
            return len(record_ids), 0
        await session.execute(
            pg_insert(DeletionReceipt)
            .values(
                [
                    {
                        "record_hash": invite_receipt_hash(record_id),
                        "record_type": "invite",
                        "deleted_at": now,
                    }
                    for record_id in record_ids
                ]
            )
            .on_conflict_do_nothing(index_elements=[DeletionReceipt.record_hash])
        )
        await session.execute(delete(Invite).where(Invite.id.in_(record_ids)))
        return len(record_ids), len(record_ids)


async def _run_auth(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Delete expired auth artifacts under the explicit global auth policy."""

    examined = deleted = 0
    async with sessions() as session, session.begin():
        policy = await session.get(AuthRetentionPolicy, 1, with_for_update=not dry_run)
        if policy is None or policy.legal_hold:
            return 0, 0

        for model, record_type, retention_days, terminal_at in (
            (
                AuthSession,
                "session",
                policy.session_retention_days,
                func.coalesce(AuthSession.revoked_at, AuthSession.expires_at),
            ),
            (
                MagicLink,
                "magic_link",
                policy.magic_link_retention_days,
                func.coalesce(MagicLink.used_at, MagicLink.expires_at),
            ),
        ):
            if retention_days is None:
                continue
            cutoff = now - timedelta(days=retention_days)
            query = (
                select(model.id)
                .where(terminal_at <= cutoff)
                .order_by(terminal_at, model.id)
                .limit(batch_size)
            )
            if not dry_run:
                query = query.with_for_update(skip_locked=True)
            record_ids = list(await session.scalars(query))
            examined += len(record_ids)
            if dry_run or not record_ids:
                continue
            await session.execute(
                pg_insert(DeletionReceipt)
                .values(
                    [
                        {
                            "record_hash": auth_receipt_hash(record_type, record_id),
                            "record_type": record_type,
                            "deleted_at": now,
                        }
                        for record_id in record_ids
                    ]
                )
                .on_conflict_do_nothing(index_elements=[DeletionReceipt.record_hash])
            )
            await session.execute(delete(model).where(model.id.in_(record_ids)))
            deleted += len(record_ids)
    return examined, deleted


async def _run_cli(*, batch_size: int, execute: bool) -> None:
    from treasurypilot_api.config import get_settings

    settings = get_settings()
    if settings.database_url is None:
        raise RuntimeError("TP_DATABASE_URL or DATABASE_URL is required")
    engine, sessions = create_session_factory(settings.database_url.get_secret_value())
    try:
        result = await run_retention(
            sessions, now=datetime.now(UTC), batch_size=batch_size, dry_run=not execute
        )
        print(f"examined={result.examined} deleted={result.deleted} failed={result.failed}")
    finally:
        await engine.dispose()
    if result.failed:
        sys.exit(1)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(description="Apply configured data retention policies")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--execute", action="store_true", help="Delete eligible rows; default is dry run"
    )
    args = parser.parse_args()
    asyncio.run(_run_cli(batch_size=args.batch_size, execute=args.execute))


if __name__ == "__main__":
    main()
