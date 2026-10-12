from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self
from urllib.parse import parse_qs, urlparse

import pytest
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
from treasurypilot_api.main import create_app


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
        return SessionAccess(self.profile.user)

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


def make_harness(*, sender_fails: bool = False) -> AuthHarness:
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
        clock=clock,
    )
    settings = Settings(environment="test", session_secret=secret.decode())
    app = create_app(settings=settings, auth_service=service)
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


def test_email_failure_invalidates_issued_token_without_leaking_provider_error() -> None:
    with make_harness(sender_fails=True) as harness:
        response = harness.client.post("/v1/auth/magic-link", json={"email": "person@example.com"})
        assert response.status_code == 503
        assert response.json()["code"] == "EMAIL_UNAVAILABLE"
        assert "sensitive" not in response.text
        assert all(link.used_at is not None for link in harness.repository.links.values())
        assert not harness.repository.sessions


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
