from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlencode

MAGIC_LINK_LIFETIME = timedelta(minutes=15)
SESSION_IDLE_LIFETIME = timedelta(minutes=30)
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("authentication clocks must return timezone-aware datetimes")
    return value.astimezone(UTC)


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_token(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def hash_client_value(value: str, secret: bytes) -> bytes:
    return hmac.digest(secret, value.encode("utf-8", errors="replace"), "sha256")


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes | None:
    try:
        encoded = value.encode("ascii")
        padded = encoded + b"=" * (-len(encoded) % 4)
        decoded = base64.b64decode(padded, altchars=b"-_", validate=True)
        if not hmac.compare_digest(_encode(decoded), value):
            return None
        return decoded
    except (ValueError, UnicodeEncodeError):
        return None


@dataclass(frozen=True, slots=True)
class UserRecord:
    id: uuid.UUID
    email: str
    display_name: str | None
    status: str


@dataclass(frozen=True, slots=True)
class MembershipRecord:
    id: uuid.UUID
    org_id: uuid.UUID
    roles: tuple[str, ...]
    status: str


@dataclass(frozen=True, slots=True)
class WalletRecord:
    address: bytes
    chain_family: str
    is_contract: bool
    linked_at: datetime


@dataclass(frozen=True, slots=True)
class ProfileRecord:
    user: UserRecord
    memberships: tuple[MembershipRecord, ...]
    wallets: tuple[WalletRecord, ...]


class ConsumeStatus(StrEnum):
    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ConsumeResult:
    status: ConsumeStatus
    user: UserRecord | None = None


@dataclass(frozen=True, slots=True)
class SessionAccess:
    user: UserRecord


class AuthRepository(Protocol):
    async def find_active_user_by_email(self, email: str) -> UserRecord | None: ...

    async def replace_magic_link(
        self,
        *,
        email: str,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None: ...

    async def invalidate_magic_link(
        self, *, token_hash: bytes, invalidated_at: datetime
    ) -> None: ...

    async def consume_magic_link(self, *, token_hash: bytes, now: datetime) -> ConsumeResult: ...

    async def create_session(
        self,
        *,
        session_id: uuid.UUID,
        user_id: uuid.UUID,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
        ip_hash: bytes,
        ua_hash: bytes,
    ) -> None: ...

    async def access_session(
        self,
        *,
        session_id: uuid.UUID,
        token_hash: bytes,
        now: datetime,
        idle_lifetime: timedelta,
    ) -> SessionAccess | None: ...

    async def revoke_session(self, *, session_id: uuid.UUID, now: datetime) -> None: ...

    async def get_profile(self, user_id: uuid.UUID) -> ProfileRecord | None: ...


class MagicLinkSender(Protocol):
    async def send_magic_link(self, *, email: str, url: str) -> None: ...


class AuthFailure(Exception):
    def __init__(self, *, status: int, code: str, title: str, detail: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail


class SessionTokenCodec:
    """Create opaque, authenticated cookie values without storing bearer tokens."""

    _SESSION_CONTEXT = b"treasurypilot/session/v1\x00"
    _CSRF_CONTEXT = b"treasurypilot/csrf/v1\x00"

    def __init__(self, secret: bytes) -> None:
        if len(secret) < 32:
            raise ValueError("session secret must contain at least 32 bytes")
        self._secret = secret

    def session_token(self, session_id: uuid.UUID) -> str:
        payload = session_id.bytes
        signature = hmac.digest(self._secret, self._SESSION_CONTEXT + payload, "sha256")
        return _encode(payload + signature)

    def parse_session_token(self, token: str) -> uuid.UUID | None:
        decoded = _decode(token)
        if decoded is None or len(decoded) != 48:
            return None
        payload, signature = decoded[:16], decoded[16:]
        expected = hmac.digest(self._secret, self._SESSION_CONTEXT + payload, "sha256")
        if not hmac.compare_digest(signature, expected):
            return None
        return uuid.UUID(bytes=payload)

    def csrf_token(self, session_id: uuid.UUID) -> str:
        nonce = secrets.token_bytes(32)
        signature = hmac.digest(
            self._secret, self._CSRF_CONTEXT + session_id.bytes + nonce, "sha256"
        )
        return _encode(nonce + signature)

    def validate_csrf_token(self, session_id: uuid.UUID, token: str) -> bool:
        decoded = _decode(token)
        if decoded is None or len(decoded) != 64:
            return False
        nonce, signature = decoded[:32], decoded[32:]
        expected = hmac.digest(
            self._secret, self._CSRF_CONTEXT + session_id.bytes + nonce, "sha256"
        )
        return hmac.compare_digest(signature, expected)


@dataclass(frozen=True, slots=True)
class VerifiedSession:
    user: UserRecord
    session_id: uuid.UUID
    session_token: str
    csrf_token: str


class AuthService:
    def __init__(
        self,
        *,
        repository: AuthRepository,
        sender: MagicLinkSender,
        token_codec: SessionTokenCodec,
        client_hash_secret: bytes,
        magic_link_base_url: str,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if len(client_hash_secret) < 32:
            raise ValueError("client hash secret must contain at least 32 bytes")
        self._repository = repository
        self._sender = sender
        self._token_codec = token_codec
        self._client_hash_secret = client_hash_secret
        self._magic_link_base_url = magic_link_base_url
        self._clock = clock

    def _now(self) -> datetime:
        return require_aware_utc(self._clock())

    async def request_magic_link(self, email: str) -> None:
        normalized = normalize_email(email)
        user = await self._repository.find_active_user_by_email(normalized)
        if user is None:
            # Perform the same token work as the known-account path. No record or usable
            # token is created, and the caller receives the same HTTP response.
            hash_token(secrets.token_urlsafe(32))
            return

        raw_token = secrets.token_urlsafe(32)
        token_digest = hash_token(raw_token)
        now = self._now()
        await self._repository.replace_magic_link(
            email=normalized,
            token_hash=token_digest,
            created_at=now,
            expires_at=now + MAGIC_LINK_LIFETIME,
        )
        separator = "&" if "?" in self._magic_link_base_url else "?"
        url = f"{self._magic_link_base_url}{separator}{urlencode({'token': raw_token})}"
        try:
            await self._sender.send_magic_link(email=normalized, url=url)
        except Exception as exc:
            await self._repository.invalidate_magic_link(
                token_hash=token_digest, invalidated_at=self._now()
            )
            raise AuthFailure(
                status=503,
                code="EMAIL_UNAVAILABLE",
                title="Email service unavailable",
                detail="The sign-in email could not be sent. Please retry.",
            ) from exc

    async def verify_magic_link(
        self, *, token: str, client_ip: str, user_agent: str
    ) -> VerifiedSession:
        now = self._now()
        result = await self._repository.consume_magic_link(token_hash=hash_token(token), now=now)
        if result.status is ConsumeStatus.EXPIRED:
            raise AuthFailure(
                status=410,
                code="TOKEN_EXPIRED",
                title="Magic link expired",
                detail="This sign-in link has expired. Request a new one.",
            )
        if result.status is not ConsumeStatus.VALID or result.user is None:
            raise AuthFailure(
                status=400,
                code="TOKEN_INVALID",
                title="Invalid magic link",
                detail="This sign-in link is invalid or has already been used.",
            )

        session_id = uuid.uuid4()
        session_token = self._token_codec.session_token(session_id)
        await self._repository.create_session(
            session_id=session_id,
            user_id=result.user.id,
            token_hash=hash_token(session_token),
            created_at=now,
            expires_at=now + SESSION_ABSOLUTE_LIFETIME,
            ip_hash=hash_client_value(client_ip, self._client_hash_secret),
            ua_hash=hash_client_value(user_agent, self._client_hash_secret),
        )
        return VerifiedSession(
            user=result.user,
            session_id=session_id,
            session_token=session_token,
            csrf_token=self._token_codec.csrf_token(session_id),
        )

    async def authenticate(
        self,
        *,
        session_token: str | None,
        csrf_cookie: str | None = None,
        csrf_header: str | None = None,
        require_csrf: bool = False,
    ) -> SessionAccess:
        if not session_token:
            raise self._authentication_required()
        session_id = self._token_codec.parse_session_token(session_token)
        if session_id is None:
            raise self._authentication_required()

        if require_csrf:
            if not csrf_cookie or not csrf_header:
                raise self._csrf_invalid()
            if not hmac.compare_digest(csrf_cookie, csrf_header):
                raise self._csrf_invalid()
            if not self._token_codec.validate_csrf_token(session_id, csrf_header):
                raise self._csrf_invalid()

        access = await self._repository.access_session(
            session_id=session_id,
            token_hash=hash_token(session_token),
            now=self._now(),
            idle_lifetime=SESSION_IDLE_LIFETIME,
        )
        if access is None:
            raise self._authentication_required()
        return access

    async def logout(
        self, *, session_token: str, csrf_cookie: str | None, csrf_header: str | None
    ) -> None:
        await self.authenticate(
            session_token=session_token,
            csrf_cookie=csrf_cookie,
            csrf_header=csrf_header,
            require_csrf=True,
        )
        session_id = self._token_codec.parse_session_token(session_token)
        if session_id is None:  # Defensive: authenticate already validated this token.
            raise self._authentication_required()
        await self._repository.revoke_session(session_id=session_id, now=self._now())

    async def profile(self, access: SessionAccess) -> ProfileRecord:
        profile = await self._repository.get_profile(access.user.id)
        if profile is None:
            raise self._authentication_required()
        return profile

    @staticmethod
    def _authentication_required() -> AuthFailure:
        return AuthFailure(
            status=401,
            code="AUTH_REQUIRED",
            title="Authentication required",
            detail="A valid session is required.",
        )

    @staticmethod
    def _csrf_invalid() -> AuthFailure:
        return AuthFailure(
            status=403,
            code="CSRF_INVALID",
            title="CSRF validation failed",
            detail="A matching CSRF cookie and header are required.",
        )
