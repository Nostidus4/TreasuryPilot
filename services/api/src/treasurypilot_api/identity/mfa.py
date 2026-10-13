"""TOTP enrollment, one-use recovery and session-bound step-up.

The repository serializes verification under row locks. A successful TOTP
counter cannot be replayed, including from another concurrent session.
"""

from __future__ import annotations

import base64
import hmac
import secrets
import struct
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import MfaRecoveryCode, MfaTotp, Session
from treasurypilot_api.identity.rate_limit import RateLimiter, RateLimiterUnavailable

TOTP_PERIOD = 30
TOTP_DIGITS = 6
ENROLLMENT_LIFETIME = timedelta(minutes=10)
STEP_UP_LIFETIME = timedelta(minutes=5)
RECOVERY_CODE_COUNT = 10
MFA_ATTEMPT_WINDOW = timedelta(minutes=15)
MFA_ATTEMPT_LIMIT = 5


def _failure(code: str, detail: str, status: int = 403) -> AuthFailure:
    return AuthFailure(status=status, code=code, title="MFA verification failed", detail=detail)


def totp_at(secret: bytes, counter: int) -> str:
    digest = hmac.digest(secret, struct.pack(">Q", counter), "sha1")
    offset = digest[-1] & 15
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % (10**TOTP_DIGITS):0{TOTP_DIGITS}d}"


def matching_counter(secret: bytes, code: str, now: datetime, last_counter: int) -> int | None:
    if len(code) != TOTP_DIGITS or not code.isascii() or not code.isdecimal():
        return None
    current = int(now.timestamp()) // TOTP_PERIOD
    for counter in (current - 1, current, current + 1):
        if (
            counter > last_counter
            and counter >= 0
            and hmac.compare_digest(totp_at(secret, counter), code)
        ):
            return counter
    return None


class MfaService:
    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], secret: bytes, limiter: RateLimiter
    ) -> None:
        if len(secret) < 32:
            raise ValueError("MFA encryption key must contain at least 32 bytes")
        self._sessions = sessions
        self._limiter = limiter
        key = base64.urlsafe_b64encode(
            hmac.digest(secret, b"treasurypilot/mfa/fernet/v1", "sha256")
        )
        self._cipher = Fernet(key)
        self._recovery_pepper = hmac.digest(secret, b"treasurypilot/mfa/recovery/v1", "sha256")

    async def _limit(self, user_id: uuid.UUID) -> None:
        key = hmac.digest(self._recovery_pepper, user_id.bytes, "sha256").hex()
        try:
            result = await self._limiter.hit(
                f"mfa:verify:{key}", limit=MFA_ATTEMPT_LIMIT, window=MFA_ATTEMPT_WINDOW
            )
        except RateLimiterUnavailable:
            raise _failure(
                "MFA_UNAVAILABLE", "Second-factor verification is unavailable.", 503
            ) from None
        if not result.allowed:
            raise AuthFailure(
                status=429,
                code="RATE_LIMITED",
                title="Too many requests",
                detail="Too many second-factor attempts. Try again later.",
                retry_after=result.retry_after,
            )

    def _recovery_hash(self, code: str) -> bytes:
        return hmac.digest(self._recovery_pepper, code.encode("ascii"), "sha256")

    async def begin_enrollment(
        self, user_id: uuid.UUID, now: datetime, issuer: str
    ) -> tuple[str, str]:
        raw_secret = secrets.token_bytes(20)
        encoded_secret = base64.b32encode(raw_secret).decode("ascii").rstrip("=")
        async with self._sessions() as db, db.begin():
            record = await db.scalar(
                select(MfaTotp).where(MfaTotp.user_id == user_id).with_for_update()
            )
            if record is not None and record.encrypted_secret is not None:
                raise _failure("MFA_ALREADY_ENROLLED", "TOTP is already enrolled.", 409)
            if record is None:
                record = MfaTotp(user_id=user_id)
                db.add(record)
            record.pending_secret = self._cipher.encrypt(raw_secret)
            record.pending_expires_at = now + ENROLLMENT_LIFETIME
        uri = (
            f"otpauth://totp/{quote(issuer)}:{user_id}"
            f"?secret={encoded_secret}&issuer={quote(issuer)}"
            f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
        )
        return encoded_secret, uri

    async def confirm_enrollment(self, user_id: uuid.UUID, code: str, now: datetime) -> list[str]:
        await self._limit(user_id)
        async with self._sessions() as db, db.begin():
            record = await db.scalar(
                select(MfaTotp).where(MfaTotp.user_id == user_id).with_for_update()
            )
            if (
                record is None
                or record.encrypted_secret is not None
                or record.pending_secret is None
                or record.pending_expires_at is None
                or now >= record.pending_expires_at
            ):
                raise _failure("MFA_ENROLLMENT_EXPIRED", "Start TOTP enrollment again.")
            try:
                secret = self._cipher.decrypt(record.pending_secret)
            except InvalidToken:
                raise _failure(
                    "MFA_UNAVAILABLE", "TOTP enrollment cannot be decrypted.", 503
                ) from None
            counter = matching_counter(secret, code, now, -1)
            if counter is None:
                raise _failure("MFA_CODE_INVALID", "The verification code is invalid.")
            recovery_codes = [secrets.token_hex(12).upper() for _ in range(RECOVERY_CODE_COUNT)]
            record.encrypted_secret = record.pending_secret
            record.pending_secret = None
            record.pending_expires_at = None
            record.last_counter = counter
            for recovery_code in recovery_codes:
                db.add(
                    MfaRecoveryCode(user_id=user_id, code_hash=self._recovery_hash(recovery_code))
                )
            return recovery_codes

    async def verify_step_up(
        self, user_id: uuid.UUID, session_id: uuid.UUID, code: str, now: datetime
    ) -> datetime:
        await self._limit(user_id)
        async with self._sessions() as db, db.begin():
            record = await db.scalar(
                select(MfaTotp).where(MfaTotp.user_id == user_id).with_for_update()
            )
            if record is None or record.encrypted_secret is None:
                raise _failure("MFA_NOT_ENROLLED", "Enroll a second factor first.")
            if len(code) == TOTP_DIGITS and code.isascii() and code.isdecimal():
                try:
                    secret = self._cipher.decrypt(record.encrypted_secret)
                except InvalidToken:
                    raise _failure("MFA_UNAVAILABLE", "TOTP cannot be decrypted.", 503) from None
                counter = matching_counter(secret, code, now, record.last_counter)
                if counter is None:
                    raise _failure("MFA_CODE_INVALID", "The verification code is invalid.")
                record.last_counter = counter
            elif len(code) == 24 and all(char in "0123456789ABCDEF" for char in code):
                recovery = await db.scalar(
                    select(MfaRecoveryCode)
                    .where(
                        MfaRecoveryCode.user_id == user_id,
                        MfaRecoveryCode.code_hash == self._recovery_hash(code),
                    )
                    .with_for_update()
                )
                if recovery is None:
                    raise _failure("MFA_CODE_INVALID", "The verification code is invalid.")
                await db.delete(recovery)
            else:
                raise _failure("MFA_CODE_INVALID", "The verification code is invalid.")
            session = await db.scalar(
                select(Session)
                .where(
                    Session.id == session_id,
                    Session.user_id == user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                )
                .with_for_update()
            )
            if session is None:
                raise _failure("AUTH_REQUIRED", "A valid session is required.", 401)
            session.step_up_at = now
            return now + STEP_UP_LIFETIME

    async def require_fresh_step_up(
        self, user_id: uuid.UUID, session_id: uuid.UUID, now: datetime
    ) -> None:
        async with self._sessions() as db:
            session = await db.scalar(
                select(Session).where(
                    Session.id == session_id,
                    Session.user_id == user_id,
                    Session.revoked_at.is_(None),
                    Session.expires_at > now,
                )
            )
            if (
                session is None
                or session.step_up_at is None
                or session.step_up_at > now
                or now - session.step_up_at >= STEP_UP_LIFETIME
            ):
                raise _failure("MFA_STEP_UP_REQUIRED", "Complete a fresh second-factor challenge.")
