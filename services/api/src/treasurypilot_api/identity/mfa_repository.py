from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.mfa import FactorRecord
from treasurypilot_api.identity.models import MfaFactor, MfaRecoveryCode, Session


def _record(row: MfaFactor) -> FactorRecord:
    return FactorRecord(
        id=row.id,
        user_id=row.user_id,
        kind=row.kind,
        label=row.label,
        secret=row.secret,
        credential_id=row.credential_id,
        public_key=row.public_key,
        sign_count=row.sign_count,
        last_counter=row.last_counter,
        created_at=row.created_at,
        confirmed_at=row.confirmed_at,
    )


class SqlAlchemyMfaRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def list_factors(self, user_id: uuid.UUID) -> list[FactorRecord]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(MfaFactor).where(MfaFactor.user_id == user_id).order_by(MfaFactor.id)
            )
            return [_record(row) for row in rows]

    async def add_factor(self, factor: FactorRecord) -> bool:
        try:
            async with self._sessions() as session, session.begin():
                session.add(
                    MfaFactor(
                        id=factor.id,
                        user_id=factor.user_id,
                        kind=factor.kind,
                        label=factor.label,
                        secret=factor.secret,
                        credential_id=factor.credential_id,
                        public_key=factor.public_key,
                        sign_count=factor.sign_count,
                        last_counter=factor.last_counter,
                        created_at=factor.created_at,
                        confirmed_at=factor.confirmed_at,
                    )
                )
        except IntegrityError:
            return False
        return True

    async def confirm_factor(self, *, factor_id: uuid.UUID, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(MfaFactor).where(MfaFactor.id == factor_id).values(confirmed_at=now)
            )

    async def delete_factor(self, *, user_id: uuid.UUID, factor_id: uuid.UUID) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                delete(MfaFactor).where(MfaFactor.id == factor_id, MfaFactor.user_id == user_id)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def advance_totp_counter(self, *, factor_id: uuid.UUID, counter: int) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(MfaFactor)
                .where(
                    MfaFactor.id == factor_id,
                    or_(MfaFactor.last_counter.is_(None), MfaFactor.last_counter < counter),
                )
                .values(last_counter=counter)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def advance_sign_count(self, *, factor_id: uuid.UUID, sign_count: int) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(MfaFactor)
                .where(MfaFactor.id == factor_id, MfaFactor.sign_count < sign_count)
                .values(sign_count=sign_count)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def replace_recovery_codes(
        self, *, user_id: uuid.UUID, code_hashes: list[bytes], now: datetime
    ) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(delete(MfaRecoveryCode).where(MfaRecoveryCode.user_id == user_id))
            session.add_all(
                MfaRecoveryCode(user_id=user_id, code_hash=digest, created_at=now)
                for digest in code_hashes
            )

    async def count_recovery_codes(self, user_id: uuid.UUID) -> int:
        async with self._sessions() as session:
            return int(
                await session.scalar(
                    select(func.count())
                    .select_from(MfaRecoveryCode)
                    .where(MfaRecoveryCode.user_id == user_id, MfaRecoveryCode.used_at.is_(None))
                )
                or 0
            )

    async def consume_recovery_code(
        self, *, user_id: uuid.UUID, code_hash: bytes, now: datetime
    ) -> bool:
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(MfaRecoveryCode)
                .where(
                    MfaRecoveryCode.user_id == user_id,
                    MfaRecoveryCode.code_hash == code_hash,
                    MfaRecoveryCode.used_at.is_(None),
                )
                .values(used_at=now)
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def mark_step_up(self, *, session_id: uuid.UUID, now: datetime) -> None:
        async with self._sessions() as session, session.begin():
            await session.execute(
                update(Session).where(Session.id == session_id).values(step_up_at=now)
            )
