from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlencode

from treasurypilot_api.identity.rate_limit import RateLimiter, RateLimiterUnavailable

MAGIC_LINK_LIFETIME = timedelta(minutes=15)
SESSION_IDLE_LIFETIME = timedelta(minutes=30)
SESSION_ABSOLUTE_LIFETIME = timedelta(hours=12)
# How long a second-factor check stays good for approve, exception and mandate routes.
STEP_UP_LIFETIME = timedelta(minutes=10)
MAX_MAGIC_LINK_TOKEN_LENGTH = 256

# Identity README section 6: 5 per 15 min per email, 20 per 15 min per IP.
RATE_LIMIT_WINDOW = timedelta(minutes=15)
# RFC 9110 §10.2.3: hint a short backoff while the limiter backend is down.
AUTH_UNAVAILABLE_RETRY_AFTER_S = 30
MAGIC_LINK_EMAIL_LIMIT = 5
MAGIC_LINK_IP_LIMIT = 20
VERIFY_IP_LIMIT = 20
SAML_START_IP_LIMIT = 20

logger = logging.getLogger(__name__)


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("authentication clocks must return timezone-aware datetimes")
    return value.astimezone(UTC)


def normalize_email(value: str) -> str:
    # PostgreSQL CITEXT compares with lower(), so casefold() would miss rows
    # such as "straße" (casefolds to "strasse").
    return value.strip().lower()


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
    owner_is_onchain: bool = False
    owner_checked_at: datetime | None = None
    signer_roles_active: bool = False


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
    session_id: uuid.UUID
    organization_scope_id: uuid.UUID | None = None
    step_up_at: datetime | None = None


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
        organization_scope_id: uuid.UUID | None = None,
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

    async def get_profile(
        self, user_id: uuid.UUID, organization_scope_id: uuid.UUID | None = None
    ) -> ProfileRecord | None: ...


class MagicLinkSender(Protocol):
    async def send_magic_link(self, *, email: str, url: str) -> None: ...


class AuthFailure(Exception):
    def __init__(
        self,
        *,
        status: int,
        code: str,
        title: str,
        detail: str,
        retry_after: int | None = None,
        extensions: dict[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.retry_after = retry_after
        self.extensions = extensions or {}


def auth_unavailable(detail: str) -> AuthFailure:
    """503 AUTH_UNAVAILABLE; every variant carries the same Retry-After hint."""

    return AuthFailure(
        status=503,
        code="AUTH_UNAVAILABLE",
        title="Authentication unavailable",
        detail=detail,
        retry_after=AUTH_UNAVAILABLE_RETRY_AFTER_S,
    )


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
class MagicLinkDelivery:
    """An issued link that still has to be sent outside the request path."""

    email: str
    url: str
    token_hash: bytes


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
        rate_limiter: RateLimiter,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if len(client_hash_secret) < 32:
            raise ValueError("client hash secret must contain at least 32 bytes")
        self._repository = repository
        self._sender = sender
        self._token_codec = token_codec
        self._client_hash_secret = client_hash_secret
        self._magic_link_base_url = magic_link_base_url
        self._rate_limiter = rate_limiter
        self._clock = clock

    def _now(self) -> datetime:
        return require_aware_utc(self._clock())

    async def _enforce_limit(self, scope: str, value: str, limit: int) -> None:
        await self._enforce_limits((scope, value, limit))

    async def _enforce_limits(self, *checks: tuple[str, str, int]) -> None:
        """Count every limit, then reject with the longest wait among those exceeded.

        Checking all of them means a client that honours Retry-After is not limited
        again by a second, longer window it had not been told about.
        """

        waits: list[int] = []
        for scope, value, limit in checks:
            # Key on a keyed hash so the limiter store never holds emails or IPs.
            digest = _encode(hash_client_value(value, self._client_hash_secret))
            try:
                result = await self._rate_limiter.hit(
                    f"{scope}:{digest}", limit=limit, window=RATE_LIMIT_WINDOW
                )
            except RateLimiterUnavailable:
                # Identity M01-D8: fail closed for auth endpoints when Redis is down.
                raise auth_unavailable(
                    "Sign-in is temporarily unavailable. Please retry."
                ) from None
            if not result.allowed:
                waits.append(result.retry_after)
        if waits:
            raise AuthFailure(
                status=429,
                code="RATE_LIMITED",
                title="Too many requests",
                detail="Too many sign-in attempts. Please wait and try again.",
                # The time left in the longest exceeded fixed window.
                retry_after=max(waits),
            )

    async def enforce_saml_start_limit(self, client_ip: str) -> None:
        await self._enforce_limit("saml-start:ip", client_ip, SAML_START_IP_LIMIT)

    async def request_magic_link(self, email: str, *, client_ip: str) -> MagicLinkDelivery | None:
        """Apply limits and issue a link for direct service callers."""

        normalized = normalize_email(email)
        await self.enforce_magic_link_limits(normalized, client_ip=client_ip)
        return await self.issue_magic_link(normalized)

    async def enforce_magic_link_limits(self, email: str, *, client_ip: str) -> None:
        """Apply shared request limits before an enumeration-safe 202 response."""
        normalized = normalize_email(email)
        await self._enforce_limits(
            ("magic-link:ip", client_ip, MAGIC_LINK_IP_LIMIT),
            ("magic-link:email", normalized, MAGIC_LINK_EMAIL_LIMIT),
        )

    async def issue_magic_link(self, email: str) -> MagicLinkDelivery | None:
        """Look up the account and issue its link outside the HTTP response path."""
        normalized = normalize_email(email)
        user = await self._repository.find_active_user_by_email(normalized)
        if user is None:
            # Perform the same token work as the known-account path. No record or usable
            # token is created, and the caller receives the same HTTP response.
            hash_token(secrets.token_urlsafe(32))
            return None

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
        return MagicLinkDelivery(email=normalized, url=url, token_hash=token_digest)

    async def issue_and_deliver_magic_link(self, email: str) -> None:
        """Issue and send a link in a background task to hide account lookup timing."""
        try:
            delivery = await self.issue_magic_link(email)
            if delivery is not None:
                await self.deliver_magic_link(delivery)
        except Exception as exc:
            # Database/provider failures happen after the indistinguishable 202 response.
            logger.warning("magic link request failed: %s", type(exc).__name__)

    async def deliver_magic_link(self, delivery: MagicLinkDelivery) -> None:
        """Send an issued link; on failure the link is invalidated and logged."""

        try:
            await self._sender.send_magic_link(email=delivery.email, url=delivery.url)
        except Exception as exc:
            await self._repository.invalidate_magic_link(
                token_hash=delivery.token_hash, invalidated_at=self._now()
            )
            # Provider errors can echo request data, so log only the error type.
            logger.warning("magic link delivery failed: %s", type(exc).__name__)

    async def verify_magic_link(
        self, *, token: str, client_ip: str, user_agent: str
    ) -> VerifiedSession:
        await self._enforce_limit("verify:ip", client_ip, VERIFY_IP_LIMIT)
        now = self._now()
        if len(token) > MAX_MAGIC_LINK_TOKEN_LENGTH:
            result = ConsumeResult(ConsumeStatus.INVALID)
        else:
            result = await self._repository.consume_magic_link(
                token_hash=hash_token(token), now=now
            )
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

    async def create_oidc_session(
        self, *, user: UserRecord, organization_id: uuid.UUID, client_ip: str, user_agent: str
    ) -> VerifiedSession:
        """Issue a short organization-scoped session for an OIDC identity."""
        return await self.create_scoped_sso_session(
            user=user,
            organization_id=organization_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    async def create_saml_session(
        self, *, user: UserRecord, organization_id: uuid.UUID, client_ip: str, user_agent: str
    ) -> VerifiedSession:
        """Issue a short organization-scoped session for a SAML identity."""
        return await self.create_scoped_sso_session(
            user=user,
            organization_id=organization_id,
            client_ip=client_ip,
            user_agent=user_agent,
        )

    async def create_scoped_sso_session(
        self, *, user: UserRecord, organization_id: uuid.UUID, client_ip: str, user_agent: str
    ) -> VerifiedSession:
        """Issue a short session so federated membership changes take effect quickly."""
        now = self._now()
        session_id = uuid.uuid4()
        session_token = self._token_codec.session_token(session_id)
        await self._repository.create_session(
            session_id=session_id,
            user_id=user.id,
            token_hash=hash_token(session_token),
            created_at=now,
            expires_at=now + timedelta(minutes=5),
            ip_hash=hash_client_value(client_ip, self._client_hash_secret),
            ua_hash=hash_client_value(user_agent, self._client_hash_secret),
            organization_scope_id=organization_id,
        )
        return VerifiedSession(
            user=user,
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

    def require_step_up(self, access: SessionAccess) -> None:
        """Reject a session whose last second-factor check is missing or older than 10 minutes."""

        now = self._now()
        if access.step_up_at is None or not (
            timedelta(0) <= now - access.step_up_at < STEP_UP_LIFETIME
        ):
            raise AuthFailure(
                status=403,
                code="STEP_UP_REQUIRED",
                title="Second factor required",
                detail="Confirm a second factor (POST /v1/me/mfa/step-up) and retry.",
            )

    async def logout(
        self, *, session_token: str | None, csrf_cookie: str | None, csrf_header: str | None
    ) -> None:
        access = await self.authenticate(
            session_token=session_token,
            csrf_cookie=csrf_cookie,
            csrf_header=csrf_header,
            require_csrf=True,
        )
        await self._repository.revoke_session(session_id=access.session_id, now=self._now())

    async def profile(self, access: SessionAccess) -> ProfileRecord:
        profile = await self._repository.get_profile(access.user.id, access.organization_scope_id)
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
