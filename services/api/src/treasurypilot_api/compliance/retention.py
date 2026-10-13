"""Run bounded retention batches against organization invitations.

The policy row is locked before checking a hold or deleting records. Writers use an
upsert on the same row, so placing a hold and a deletion cannot pass each other.
Callers own the transaction for policy changes; the runner owns its transactions.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import String, cast, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditLog
from treasurypilot_api.compliance.models import DeletionReceipt, RetentionPolicy
from treasurypilot_api.database import create_session_factory
from treasurypilot_api.identity.models import Invite


def invite_receipt_hash(record_id: uuid.UUID) -> bytes:
    """Hash a random UUID, never an email, token or other personal field."""

    return hashlib.sha256(b"treasurypilot:invite:v1:" + record_id.bytes).digest()


async def configure_policy(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    invite_retention_days: int | None,
    legal_hold: bool,
) -> None:
    """Set the policy atomically. ``None`` disables scheduled invite deletion."""

    if invite_retention_days is not None and invite_retention_days < 0:
        raise ValueError("invite_retention_days must be non-negative")
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


@dataclass(frozen=True, slots=True)
class RetentionResult:
    examined: int
    deleted: int


async def run_retention(
    sessions: async_sessionmaker[AsyncSession],
    *,
    now: datetime,
    batch_size: int = 100,
    dry_run: bool = True,
) -> RetentionResult:
    """Process at most one bounded batch per organization, oldest first.

    Each organization has a separate transaction. Any failure rolls back both the
    deletion and its receipt; a retry is safe and does not duplicate receipts.
    """

    if now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    if not 1 <= batch_size <= 1000:
        raise ValueError("batch_size must be between 1 and 1000")

    examined = deleted = 0
    async with sessions() as session:
        org_ids = list(await session.scalars(select(RetentionPolicy.org_id)))

    for org_id in org_ids:
        async with sessions() as session, session.begin():
            policy = await session.get(RetentionPolicy, org_id, with_for_update=True)
            if policy is None or policy.legal_hold or policy.invite_retention_days is None:
                continue
            cutoff = now - timedelta(days=policy.invite_retention_days)
            records = list(
                await session.scalars(
                    select(Invite)
                    .where(
                        Invite.org_id == org_id,
                        Invite.expires_at <= cutoff,
                        # The hash chain is immutable. Keep the source record when
                        # an audit entry still names its id or email.
                        ~exists(
                            select(AuditLog.seq).where(
                                AuditLog.org_id == Invite.org_id,
                                or_(
                                    AuditLog.entity_id == cast(Invite.id, String),
                                    AuditLog.actor_id == cast(Invite.email, String),
                                    func.strpos(
                                        cast(AuditLog.data, String), cast(Invite.email, String)
                                    )
                                    > 0,
                                ),
                            )
                        ),
                    )
                    .order_by(Invite.expires_at, Invite.id)
                    .limit(batch_size)
                    .with_for_update(skip_locked=True)
                )
            )
            examined += len(records)
            if dry_run:
                continue
            for record in records:
                session.add(
                    DeletionReceipt(
                        record_hash=invite_receipt_hash(record.id),
                        record_type="invite",
                        deleted_at=now,
                    )
                )
                await session.delete(record)
            deleted += len(records)

    return RetentionResult(examined=examined, deleted=deleted)


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
        print(f"examined={result.examined} deleted={result.deleted}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply configured invitation retention policies")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--execute", action="store_true", help="Delete eligible rows; default is dry run"
    )
    args = parser.parse_args()
    asyncio.run(_run_cli(batch_size=args.batch_size, execute=args.execute))


if __name__ == "__main__":
    main()
