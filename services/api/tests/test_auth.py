from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import (
    AuthService,
    ConsumeResult,
    ConsumeStatus,
    MembershipRecord,
    ProfileRecord,
    SessionAccess,
    SessionTokenCodec,
    UserRecord,
    WalletRecord,
)
from treasurypilot_api.identity.email import ConsoleMagicLinkSender
from treasurypilot_api.identity.organizations import (
    OnboardingChecklist,
    OrganizationNotFound,
    OrganizationOverview,
    OrganizationPermissionDenied,
    OrganizationRecord,
)
from treasurypilot_api.identity.rate_limit import (
    MemoryRateLimiter,
    RateLimiterUnavailable,
    RateLimitResult,
)
from treasurypilot_api.main import create_app
from treasurypilot_api.treasury.config import ChainConfig, PlatformConfiguration
from treasurypilot_api.treasury.sync import asset_id


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, delta: timedelta) -> None:
        self.value += delta


@dataclass
class StoredMagicLink:
    email: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None


@dataclass
class StoredSession:
    user_id: uuid.UUID
    token_hash: bytes
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    ip_hash: bytes
    ua_hash: bytes
    revoked_at: datetime | None = None


class MemoryAuthRepository:
    def __init__(self, user: UserRecord) -> None:
        self.users = {user.email: user}
        self.links: dict[bytes, StoredMagicLink] = {}
        self.sessions: dict[uuid.UUID, StoredSession] = {}
        membership = MembershipRecord(
            id=uuid.UUID("00000000-0000-4000-8000-000000000011"),
            org_id=uuid.UUID("00000000-0000-4000-8000-000000000012"),
            roles=("Finance", "Auditor"),
            status="active",
        )
        wallet = WalletRecord(
            address=bytes.fromhex("11" * 20),
            chain_family="evm",
            is_contract=False,
            linked_at=datetime(2026, 10, 1, tzinfo=UTC),
        )
        self.profile = ProfileRecord(user=user, memberships=(membership,), wallets=(wallet,))

    async def find_active_user_by_email(self, email: str) -> UserRecord | None:
        user = self.users.get(email)
        return user if user is not None and user.status == "active" else None

    async def replace_magic_link(
        self,
        *,
        email: str,
        token_hash: bytes,
        created_at: datetime,
        expires_at: datetime,
    ) -> None:
        for link in self.links.values():
            if link.email == email and link.used_at is None:
                link.used_at = created_at
        self.links[token_hash] = StoredMagicLink(email, created_at, expires_at)

    async def invalidate_magic_link(self, *, token_hash: bytes, invalidated_at: datetime) -> None:
        link = self.links.get(token_hash)
        if link is not None and link.used_at is None:
            link.used_at = invalidated_at

    async def consume_magic_link(self, *, token_hash: bytes, now: datetime) -> ConsumeResult:
        link = self.links.get(token_hash)
        if link is None or link.used_at is not None:
            return ConsumeResult(ConsumeStatus.INVALID)
        if now >= link.expires_at:
            return ConsumeResult(ConsumeStatus.EXPIRED)
        user = self.users.get(link.email)
        if user is None or user.status != "active":
            return ConsumeResult(ConsumeStatus.INVALID)
        link.used_at = now
        return ConsumeResult(ConsumeStatus.VALID, user)

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
    ) -> None:
        self.sessions[session_id] = StoredSession(
            user_id=user_id,
            token_hash=token_hash,
            created_at=created_at,
            expires_at=expires_at,
            last_seen_at=created_at,
            ip_hash=ip_hash,
            ua_hash=ua_hash,
        )

    async def access_session(
        self,
        *,
        session_id: uuid.UUID,
        token_hash: bytes,
        now: datetime,
        idle_lifetime: timedelta,
    ) -> SessionAccess | None:
        session = self.sessions.get(session_id)
        if session is None or session.revoked_at is not None or session.token_hash != token_hash:
            return None
        if now >= session.expires_at or now - session.last_seen_at >= idle_lifetime:
            session.revoked_at = now
            return None
        session.last_seen_at = now
        return SessionAccess(self.profile.user, session_id)

    async def revoke_session(self, *, session_id: uuid.UUID, now: datetime) -> None:
        session = self.sessions.get(session_id)
        if session is not None and session.revoked_at is None:
            session.revoked_at = now

    async def get_profile(self, user_id: uuid.UUID) -> ProfileRecord | None:
        return self.profile if self.profile.user.id == user_id else None


class CaptureSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.messages: list[tuple[str, str]] = []
        self.fail = fail

    async def send_magic_link(self, *, email: str, url: str) -> None:
        if self.fail:
            raise RuntimeError("provider response containing sensitive request data")
        self.messages.append((email, url))


@dataclass
class AuthHarness:
    clock: MutableClock
    repository: MemoryAuthRepository
    sender: CaptureSender
    client: TestClient

    def request_token(self, email: str = "person@example.com") -> str:
        response = self.client.post("/v1/auth/magic-link", json={"email": email})
        assert response.status_code == 202
        url = self.sender.messages[-1][1]
        return parse_qs(urlparse(url).query)["token"][0]

    def verify(self, token: str) -> object:
        response = self.client.post("/v1/auth/magic-link/verify", json={"token": token})
        assert response.status_code == 200
        return response

    def login(self) -> str:
        token = self.request_token()
        self.verify(token)
        return token

    def __enter__(self) -> Self:
        self.client.__enter__()
        return self

    def __exit__(self, *args: object) -> None:
        self.client.__exit__(*args)


class UnavailableRateLimiter:
    async def hit(self, key: str, *, limit: int, window: timedelta) -> RateLimitResult:
        raise RateLimiterUnavailable


def make_harness(
    *,
    sender_fails: bool = False,
    rate_limiter: object | None = None,
    organization_repository: object | None = None,
) -> AuthHarness:
    clock = MutableClock()
    user = UserRecord(
        id=uuid.UUID("00000000-0000-4000-8000-000000000001"),
        email="person@example.com",
        display_name="Demo Person",
        status="active",
    )
    repository = MemoryAuthRepository(user)
    sender = CaptureSender(fail=sender_fails)
    secret = b"deterministic-test-secret-value!"
    service = AuthService(
        repository=repository,
        sender=sender,
        token_codec=SessionTokenCodec(secret),
        client_hash_secret=secret,
        magic_link_base_url="https://app.example.test/auth/verify",
        rate_limiter=rate_limiter or MemoryRateLimiter(clock),  # type: ignore[arg-type]
        clock=clock,
    )
    settings = Settings(environment="test", session_secret=secret.decode())
    app = create_app(
        settings=settings,
        auth_service=service,
        organization_repository=organization_repository,  # type: ignore[arg-type]
    )
    return AuthHarness(
        clock=clock,
        repository=repository,
        sender=sender,
        client=TestClient(app, base_url="https://app.example.test"),
    )


def test_known_and_unknown_magic_link_requests_have_identical_responses() -> None:
    with make_harness() as harness:
        known = harness.client.post("/v1/auth/magic-link", json={"email": "  PERSON@example.com "})
        known_messages = len(harness.sender.messages)
        unknown = harness.client.post("/v1/auth/magic-link", json={"email": "unknown@example.com"})

        assert (known.status_code, known.content, known.headers.get("content-type")) == (
            unknown.status_code,
            unknown.content,
            unknown.headers.get("content-type"),
        )
        assert known.status_code == 202
        assert known_messages == 1
        assert len(harness.sender.messages) == 1
        assert len(harness.repository.links) == 1


def test_valid_token_creates_server_session_and_is_single_use() -> None:
    with make_harness() as harness:
        token = harness.request_token()
        response = harness.verify(token)

        assert response.json()["user"] == {
            "id": "00000000-0000-4000-8000-000000000001",
            "email": "person@example.com",
            "displayName": "Demo Person",
            "status": "active",
        }
        assert len(harness.repository.sessions) == 1
        assert hashlib.sha256(token.encode("ascii")).digest() in harness.repository.links
        assert token.encode() not in repr(harness.repository.links).encode()

        cookie_headers = response.headers.get_list("set-cookie")
        session_cookie = next(item for item in cookie_headers if item.startswith("tp_session="))
        csrf_cookie = next(item for item in cookie_headers if item.startswith("tp_csrf="))
        assert "HttpOnly" in session_cookie
        assert "Secure" in session_cookie
        assert "SameSite=lax" in session_cookie
        assert "HttpOnly" not in csrf_cookie
        assert "Secure" in csrf_cookie
        assert "SameSite=lax" in csrf_cookie

        reused = harness.client.post("/v1/auth/magic-link/verify", json={"token": token})
        assert reused.status_code == 400
        assert reused.headers["content-type"].startswith("application/problem+json")
        assert reused.json()["code"] == "TOKEN_INVALID"


def test_token_is_valid_before_deadline_and_expired_at_exact_deadline() -> None:
    with make_harness() as harness:
        still_valid = harness.request_token()
        harness.clock.advance(timedelta(minutes=15) - timedelta(microseconds=1))
        harness.verify(still_valid)

    with make_harness() as harness:
        expired = harness.request_token()
        harness.clock.advance(timedelta(minutes=15))
        response = harness.client.post("/v1/auth/magic-link/verify", json={"token": expired})
        assert response.status_code == 410
        assert response.json()["code"] == "TOKEN_EXPIRED"
        assert not harness.repository.sessions


def test_me_returns_current_user_memberships_and_linked_wallets() -> None:
    with make_harness() as harness:
        harness.login()
        response = harness.client.get("/v1/me")

        assert response.status_code == 200
        payload = response.json()
        assert payload["user"]["email"] == "person@example.com"
        assert payload["memberships"] == [
            {
                "id": "00000000-0000-4000-8000-000000000011",
                "orgId": "00000000-0000-4000-8000-000000000012",
                "roles": ["Finance", "Auditor"],
                "status": "active",
            }
        ]
        assert payload["wallets"][0]["address"] == "0x" + "11" * 20


def test_session_idle_timeout_rejects_31_minutes_and_exact_boundary() -> None:
    with make_harness() as harness:
        harness.login()
        harness.clock.advance(timedelta(minutes=31))
        response = harness.client.get("/v1/me")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"

    with make_harness() as harness:
        harness.login()
        harness.clock.advance(timedelta(minutes=30))
        assert harness.client.get("/v1/me").status_code == 401


def test_session_activity_refreshes_idle_window_but_not_absolute_expiry() -> None:
    with make_harness() as harness:
        harness.login()
        for _ in range(24):
            harness.clock.advance(timedelta(minutes=29))
            assert harness.client.get("/v1/me").status_code == 200
        harness.clock.value = datetime(2026, 10, 12, 20, 0, tzinfo=UTC)
        response = harness.client.get("/v1/me")
        assert response.status_code == 401
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_logout_requires_double_submit_csrf_and_revokes_session() -> None:
    with make_harness() as harness:
        harness.login()
        missing = harness.client.post("/v1/auth/logout")
        assert missing.status_code == 403
        assert missing.json()["code"] == "CSRF_INVALID"

        mismatch = harness.client.post("/v1/auth/logout", headers={"X-CSRF-Token": "different"})
        assert mismatch.status_code == 403

        csrf = harness.client.cookies.get("tp_csrf")
        session_cookie = harness.client.cookies.get("tp_session")
        success = harness.client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})
        assert success.status_code == 204
        assert not harness.client.cookies.get("tp_session")
        assert not harness.client.cookies.get("tp_csrf")

        harness.client.cookies.set("tp_session", session_cookie)
        assert harness.client.get("/v1/me").status_code == 401


def test_tampered_session_and_csrf_tokens_are_rejected() -> None:
    with make_harness() as harness:
        harness.login()
        raw_session = harness.client.cookies.get("tp_session")
        raw_csrf = harness.client.cookies.get("tp_csrf")
        tampered_session = ("A" if raw_session[0] != "A" else "B") + raw_session[1:]
        harness.client.cookies.set("tp_session", tampered_session)
        assert harness.client.get("/v1/me").status_code == 401

        harness.client.cookies.set("tp_session", raw_session)
        tampered_csrf = ("A" if raw_csrf[0] != "A" else "B") + raw_csrf[1:]
        harness.client.cookies.set("tp_csrf", tampered_csrf)
        response = harness.client.post("/v1/auth/logout", headers={"X-CSRF-Token": tampered_csrf})
        assert response.status_code == 403
        assert response.json()["code"] == "CSRF_INVALID"


def test_session_and_csrf_codec_round_trip_and_tamper_detection() -> None:
    codec = SessionTokenCodec(b"deterministic-test-secret-value!")
    session_id = uuid.UUID("00000000-0000-4000-8000-000000000099")

    session_token = codec.session_token(session_id)
    csrf_token = codec.csrf_token(session_id)

    assert codec.parse_session_token(session_token) == session_id
    assert codec.validate_csrf_token(session_id, csrf_token)
    assert codec.parse_session_token(session_token[:-1] + "!") is None
    assert not codec.validate_csrf_token(session_id, csrf_token[:-1] + "!")
    assert not codec.validate_csrf_token(uuid.uuid4(), csrf_token)


def test_unicode_verify_token_returns_token_invalid_instead_of_server_error() -> None:
    with make_harness() as harness:
        response = harness.client.post("/v1/auth/magic-link/verify", json={"token": "å" * 32})
        assert response.status_code == 400
        assert response.json()["code"] == "TOKEN_INVALID"


def test_empty_and_short_verify_tokens_return_stable_invalid_error() -> None:
    with make_harness() as harness:
        for token in ("", "short"):
            response = harness.client.post("/v1/auth/magic-link/verify", json={"token": token})
            assert response.status_code == 400
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["code"] == "TOKEN_INVALID"


def test_console_sender_outputs_usable_local_link_without_recipient() -> None:
    output: list[str] = []
    sender = ConsoleMagicLinkSender(write=output.append)
    url = "http://localhost:5173/auth/verify?token=one-time-secret"

    import asyncio

    asyncio.run(sender.send_magic_link(email="person@example.com", url=url))

    assert output == [f"TreasuryPilot local magic link (secret; do not share): {url}"]
    assert "person@example.com" not in output[0]


def test_email_failure_invalidates_issued_token_without_revealing_the_account(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with make_harness(sender_fails=True) as harness:
        known = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        unknown = harness.client.post("/v1/auth/magic-link", json={"email": "nobody@example.com"})

        assert known.status_code == unknown.status_code == 202
        assert known.content == unknown.content
        assert harness.repository.links
        assert all(link.used_at is not None for link in harness.repository.links.values())
        assert not harness.repository.sessions
        assert "magic link delivery failed" in caplog.text
        assert "sensitive" not in caplog.text


def test_magic_link_requests_are_rate_limited_per_email_for_known_and_unknown() -> None:
    with make_harness() as harness:
        for email in ("person@example.com", "nobody@example.com"):
            statuses = [
                harness.client.post("/v1/auth/magic-link", json={"email": email}).status_code
                for _ in range(6)
            ]
            assert statuses == [202] * 5 + [429]

        limited = harness.client.post("/v1/auth/magic-link", json={"email": "PERSON@example.com"})
        assert limited.json()["code"] == "RATE_LIMITED"
        assert limited.headers["Retry-After"] == "900"
        assert len(harness.sender.messages) == 5

        # Retry-After is what is left of the fixed window, not its full length.
        harness.clock.advance(timedelta(minutes=14, seconds=50))
        later = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        assert later.status_code == 429
        assert later.headers["Retry-After"] == "10"
        harness.clock.advance(timedelta(seconds=10))
        assert (
            harness.client.post(
                "/v1/auth/magic-link", json={"email": "person@example.com"}
            ).status_code
            == 202
        )

        harness.clock.advance(timedelta(minutes=15))
        assert (
            harness.client.post(
                "/v1/auth/magic-link", json={"email": "person@example.com"}
            ).status_code
            == 202
        )


def test_magic_link_requests_are_rate_limited_per_ip() -> None:
    with make_harness() as harness:
        statuses = [
            harness.client.post(
                "/v1/auth/magic-link", json={"email": f"user{index}@example.com"}
            ).status_code
            for index in range(21)
        ]
        assert statuses == [202] * 20 + [429]


def test_verify_is_rate_limited_per_ip() -> None:
    with make_harness() as harness:
        statuses = [
            harness.client.post("/v1/auth/magic-link/verify", json={"token": "bad"}).status_code
            for _ in range(21)
        ]
        assert statuses == [400] * 20 + [429]
        rejected = harness.client.post("/v1/auth/magic-link/verify", json={"token": "bad"})
        assert 1 <= int(rejected.headers["Retry-After"]) <= 900
        # Only rate limits and outages carry Retry-After.
        harness.clock.advance(timedelta(minutes=15))
        invalid = harness.client.post("/v1/auth/magic-link/verify", json={"token": "bad"})
        assert invalid.status_code == 400
        assert "Retry-After" not in invalid.headers


def test_auth_endpoints_fail_closed_when_the_rate_limiter_is_down() -> None:
    with make_harness(rate_limiter=UnavailableRateLimiter()) as harness:
        response = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        assert response.status_code == 503
        assert response.json()["code"] == "AUTH_UNAVAILABLE"
        assert response.headers["Retry-After"] == "30"
        assert not harness.sender.messages


def test_verify_returns_csrf_token_for_cross_origin_clients() -> None:
    with make_harness() as harness:
        response = harness.verify(harness.request_token())

        assert response.json()["csrfToken"] == harness.client.cookies.get("tp_csrf")


def test_logout_with_expired_session_still_clears_cookies() -> None:
    with make_harness() as harness:
        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        harness.clock.advance(timedelta(minutes=31))

        response = harness.client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})

        assert response.status_code == 401
        assert not harness.client.cookies.get("tp_session")
        assert not harness.client.cookies.get("tp_csrf")


def test_oversized_verify_token_returns_token_invalid() -> None:
    with make_harness() as harness:
        response = harness.client.post("/v1/auth/magic-link/verify", json={"token": "a" * 4096})
        assert response.status_code == 400
        assert response.json()["code"] == "TOKEN_INVALID"


def test_email_normalization_matches_citext_lower() -> None:
    with make_harness() as harness:
        user = harness.repository.users.pop("person@example.com")
        harness.repository.users["straße@example.com"] = UserRecord(
            id=user.id, email="straße@example.com", display_name=None, status="active"
        )

        harness.request_token("STRAßE@example.com")

        assert harness.sender.messages[-1][0] == "straße@example.com"


def test_test_environment_is_treated_as_deployed() -> None:
    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_app(settings=Settings(environment="test", database_url=None))


def test_local_processes_share_a_session_secret() -> None:
    first = create_app(settings=Settings(environment="local"))
    second = create_app(settings=Settings(environment="local"))
    session_id = uuid.uuid4()

    token = first.state.auth_service._token_codec.session_token(session_id)

    assert second.state.auth_service._token_codec.parse_session_token(token) == session_id


def test_deployed_configuration_fails_closed_without_security_settings() -> None:
    settings = Settings(environment="production", database_url=None, session_secret=None)
    try:
        create_app(settings=settings)
    except ValueError as exc:
        assert "DATABASE_URL" in str(exc)
    else:
        raise AssertionError("production app accepted missing auth configuration")


def test_deployed_configuration_requires_https_secret_and_resend() -> None:
    database_url = "postgresql+asyncpg://user:secret@example.test/database"
    valid_secret = "a-high-entropy-session-secret-value"

    invalid_settings = (
        (
            Settings(
                environment="production",
                database_url=database_url,
                session_secret=valid_secret,
                magic_link_base_url="http://app.example.test/auth/verify",
                resend_api_key="resend-key",
                resend_from_email="login@example.test",
                redis_url="redis://redis.example.test:6379/0",
            ),
            "HTTPS",
        ),
        (
            Settings(
                environment="production",
                database_url=database_url,
                session_secret="too-short",
                magic_link_base_url="https://app.example.test/auth/verify",
                resend_api_key="resend-key",
                resend_from_email="login@example.test",
                redis_url="redis://redis.example.test:6379/0",
            ),
            "32 bytes",
        ),
        (
            Settings(
                environment="production",
                database_url=database_url,
                session_secret=valid_secret,
                magic_link_base_url="https://app.example.test/auth/verify",
            ),
            "TP_RESEND_API_KEY",
        ),
    )

    for settings, message in invalid_settings:
        with pytest.raises(ValueError, match=message):
            create_app(settings=settings)


def test_secret_settings_are_redacted_from_representations() -> None:
    database_url = "postgresql+asyncpg://user:database-secret@example.test/database"
    session_secret = "session-secret-value-that-is-long-enough"
    resend_key = "resend-secret-value"
    settings = Settings(
        database_url=database_url,
        session_secret=session_secret,
        resend_api_key=resend_key,
    )

    rendered = repr(settings)
    assert database_url not in rendered
    assert session_secret not in rendered
    assert resend_key not in rendered


class MemoryOrganizationRepository:
    def __init__(self) -> None:
        self.organizations: dict[uuid.UUID, OrganizationRecord] = {}
        self.memberships: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = {}
        self.wallets: set[uuid.UUID] = set()
        self.treasuries: set[uuid.UUID] = set()
        self.enabled_modules: set[uuid.UUID] = set()

    async def member_roles(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> frozenset[str] | None:
        roles = self.memberships.get((organization_id, user_id))
        return None if roles is None else frozenset(roles)

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        legal_name: str | None,
        country: str | None,
        display_tz: str,
    ) -> OrganizationRecord:
        organization = OrganizationRecord(
            id=uuid.uuid4(),
            name=name,
            legal_name=legal_name,
            country=country,
            display_tz=display_tz,
            solo_mode=False,
            auto_match=True,
            created_at=datetime(2026, 10, 13, tzinfo=UTC),
        )
        self.organizations[organization.id] = organization
        self.memberships[(organization.id, user_id)] = {"OrgAdmin"}
        return organization

    async def get_for_member(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID
    ) -> OrganizationOverview:
        organization = self.organizations.get(organization_id)
        if organization is None or (organization_id, user_id) not in self.memberships:
            raise OrganizationNotFound
        member_count = sum(1 for org_id, _ in self.memberships if org_id == organization_id)
        return OrganizationOverview(
            organization=organization,
            checklist=OnboardingChecklist(
                member_count=member_count,
                wallet_linked=organization_id in self.wallets,
                treasury_created=organization_id in self.treasuries,
                module_enabled=organization_id in self.enabled_modules,
            ),
        )

    async def update_settings(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        solo_mode: bool | None,
        auto_match: bool | None,
    ) -> OrganizationRecord:
        organization = self.organizations.get(organization_id)
        roles = self.memberships.get((organization_id, user_id))
        if organization is None or roles is None:
            raise OrganizationNotFound
        if solo_mode is not None and "Owner" not in roles:
            raise OrganizationPermissionDenied
        if auto_match is not None and not roles.intersection({"OrgAdmin", "Owner"}):
            raise OrganizationPermissionDenied
        updated = OrganizationRecord(
            id=organization.id,
            name=organization.name,
            legal_name=organization.legal_name,
            country=organization.country,
            display_tz=organization.display_tz,
            solo_mode=organization.solo_mode if solo_mode is None else solo_mode,
            auto_match=organization.auto_match if auto_match is None else auto_match,
            created_at=organization.created_at,
        )
        self.organizations[organization_id] = updated
        return updated


def test_create_organization_assigns_org_admin_and_checklist_uses_data() -> None:
    organizations = MemoryOrganizationRepository()
    with make_harness(organization_repository=organizations) as harness:
        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        response = harness.client.post(
            "/v1/orgs",
            json={"name": "  Acme  ", "country": "vn"},
            headers={"X-CSRF-Token": csrf},
        )

        assert response.status_code == 201
        body = response.json()
        organization_id = uuid.UUID(body["org"]["id"])
        assert body["org"]["name"] == "Acme"
        assert body["org"]["country"] == "VN"
        assert organizations.memberships[(organization_id, harness.repository.profile.user.id)] == {
            "OrgAdmin"
        }

        detail = harness.client.get(f"/v1/orgs/{organization_id}")
        assert detail.status_code == 200
        assert detail.json()["checklist"] == {
            "memberCount": 1,
            "walletLinked": False,
            "treasuryCreated": False,
            "moduleEnabled": False,
        }

        organizations.treasuries.add(organization_id)
        organizations.enabled_modules.add(organization_id)
        updated_detail = harness.client.get(f"/v1/orgs/{organization_id}")
        assert updated_detail.json()["checklist"]["treasuryCreated"] is True
        assert updated_detail.json()["checklist"]["moduleEnabled"] is True


def test_organization_routes_hide_non_members_and_restrict_solo_mode() -> None:
    organizations = MemoryOrganizationRepository()
    with make_harness(organization_repository=organizations) as harness:
        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        created = harness.client.post(
            "/v1/orgs",
            json={"name": "Acme"},
            headers={"X-CSRF-Token": csrf},
        )
        organization_id = uuid.UUID(created.json()["org"]["id"])

        hidden = harness.client.get(f"/v1/orgs/{uuid.uuid4()}")
        assert hidden.status_code == 404

        admin_setting = harness.client.patch(
            f"/v1/orgs/{organization_id}/settings",
            json={"autoMatch": False},
            headers={"X-CSRF-Token": csrf},
        )
        assert admin_setting.status_code == 200
        assert admin_setting.json()["org"]["autoMatch"] is False

        denied = harness.client.patch(
            f"/v1/orgs/{organization_id}/settings",
            json={"soloMode": True},
            headers={"X-CSRF-Token": csrf},
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "FORBIDDEN"

        organizations.memberships[(organization_id, harness.repository.profile.user.id)] = {"Owner"}
        owner_setting = harness.client.patch(
            f"/v1/orgs/{organization_id}/settings",
            json={"soloMode": True},
            headers={"X-CSRF-Token": csrf},
        )
        assert owner_setting.status_code == 200
        assert owner_setting.json()["org"]["soloMode"] is True


def test_organization_input_is_validated_and_settings_require_authentication() -> None:
    organizations = MemoryOrganizationRepository()
    with make_harness(organization_repository=organizations) as harness:
        anonymous = harness.client.patch(f"/v1/orgs/{uuid.uuid4()}/settings", json={})
        assert anonymous.status_code == 401

        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        for payload in (
            {"name": "Acme", "country": "1a"},
            {"name": "Acme", "displayTz": "Not/AZone"},
        ):
            response = harness.client.post("/v1/orgs", json=payload, headers={"X-CSRF-Token": csrf})
            assert response.status_code == 422
        assert organizations.organizations == {}

        created = harness.client.post(
            "/v1/orgs",
            json={"name": "Acme", "displayTz": "Asia/Ho_Chi_Minh"},
            headers={"X-CSRF-Token": csrf},
        )
        assert created.status_code == 201
        assert created.json()["org"]["displayTz"] == "Asia/Ho_Chi_Minh"


def _org_scoped_routes(app: FastAPI) -> list[tuple[str, str]]:
    # shortcut: routes with include_in_schema=False are invisible here; walk the router if any appear.
    return sorted(
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        # Any path parameter name for the org ({organization_id}, {orgId}, ...) counts.
        if path.startswith("/v1/orgs/{")
        for method in operations
    )


def test_every_org_scoped_route_returns_404_to_non_members() -> None:
    organizations = MemoryOrganizationRepository()
    with make_harness(organization_repository=organizations) as harness:
        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        created = harness.client.post(
            "/v1/orgs", json={"name": "Other org"}, headers={"X-CSRF-Token": csrf}
        )
        organization_id = uuid.UUID(created.json()["org"]["id"])
        # The org exists but belongs to someone else.
        organizations.memberships = {(organization_id, uuid.uuid4()): {"OrgAdmin", "Owner"}}

        routes = _org_scoped_routes(harness.client.app)  # type: ignore[arg-type]
        assert ("GET", "/v1/orgs/{organization_id}") in routes
        assert ("PATCH", "/v1/orgs/{organization_id}/settings") in routes
        for method, path in routes:
            # Any other path parameter gets a random id; the org check must win first.
            url = re.sub(r"\{[^}]+\}", str(organization_id), path, count=1)
            url = re.sub(r"\{[^}]+\}", str(uuid.uuid4()), url)
            response = harness.client.request(method, url, json={}, headers={"X-CSRF-Token": csrf})
            assert response.status_code == 404, (method, path, response.text)
            assert response.json()["code"] == "ORG_NOT_FOUND"


def test_member_without_required_role_gets_403_before_input_validation() -> None:
    organizations = MemoryOrganizationRepository()
    with make_harness(organization_repository=organizations) as harness:
        harness.login()
        csrf = harness.client.cookies.get("tp_csrf")
        created = harness.client.post(
            "/v1/orgs", json={"name": "Acme"}, headers={"X-CSRF-Token": csrf}
        )
        organization_id = uuid.UUID(created.json()["org"]["id"])
        user_id = harness.repository.profile.user.id
        organizations.memberships[(organization_id, user_id)] = {"Finance"}

        assert harness.client.get(f"/v1/orgs/{organization_id}").status_code == 200
        denied = harness.client.patch(
            f"/v1/orgs/{organization_id}/settings", json={}, headers={"X-CSRF-Token": csrf}
        )
        assert denied.status_code == 403
        assert denied.json()["code"] == "FORBIDDEN"

        missing_csrf = harness.client.patch(
            f"/v1/orgs/{organization_id}/settings", json={"autoMatch": False}
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["code"] == "CSRF_INVALID"


def _configured_chain(chain_id: int, *, enabled: bool) -> ChainConfig:
    return ChainConfig.model_validate(
        {
            "chainId": chain_id,
            "name": f"Chain {chain_id}",
            "isTestnet": True,
            "confirmations": 3,
            "explorerUrl": "https://explorer.example",
            "rpcUrls": ["https://rpc-one.example", "https://rpc-two.example"],
            "enabled": enabled,
            "assets": [
                {
                    "address": "0x" + "AB" * 20,
                    "symbol": "tUSDC",
                    "decimals": 6,
                    "issuerLabel": "TreasuryPilot test token",
                    "isTest": True,
                }
            ],
        }
    )


def test_chains_list_enabled_chains_with_test_assets_labelled() -> None:
    with make_harness() as harness:
        harness.client.app.state.platform_configuration = PlatformConfiguration(  # type: ignore[attr-defined]
            chains=(
                _configured_chain(11155111, enabled=True),
                _configured_chain(1, enabled=False),
            ),
            manifests=(),
        )
        assert harness.client.get("/v1/chains").status_code == 401

        harness.login()
        response = harness.client.get("/v1/chains")

        assert response.status_code == 200
        assert response.json() == {
            "chains": [
                {
                    "chainId": 11155111,
                    "name": "Chain 11155111",
                    "explorerUrl": "https://explorer.example/",
                    "assets": [
                        {
                            "id": str(asset_id(11155111, "0x" + "ab" * 20)),
                            "symbol": "tUSDC",
                            "decimals": 6,
                            "address": "0x" + "ab" * 20,
                            "isTest": True,
                        }
                    ],
                }
            ]
        }


def test_retry_after_is_readable_cross_origin() -> None:
    with make_harness() as harness:
        response = harness.client.post(
            "/v1/auth/magic-link",
            json={"email": "person@example.com"},
            headers={"Origin": "http://localhost:5173"},
        )
        exposed = response.headers.get("Access-Control-Expose-Headers", "")
        assert "Retry-After" in exposed


def test_retry_after_covers_the_longest_exceeded_limit() -> None:
    with make_harness() as harness:
        # Exhaust the per-IP limit (20) ten minutes before the per-email limit (5).
        for index in range(15):
            harness.client.post("/v1/auth/magic-link", json={"email": f"u{index}@example.com"})
        harness.clock.advance(timedelta(minutes=10))
        for _ in range(5):
            harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})

        limited = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "900"  # the email window, not the IP's 300

        harness.clock.advance(timedelta(seconds=900))
        retried = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        assert retried.status_code == 202


def test_unconfigured_auth_storage_sends_retry_after() -> None:
    app = create_app(settings=Settings(environment="local"))
    with TestClient(app, base_url="https://app.example.test") as client:
        response = client.post("/v1/auth/magic-link/verify", json={"token": "x" * 43})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "30"
