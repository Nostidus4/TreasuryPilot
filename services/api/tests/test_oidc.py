from __future__ import annotations

import asyncio
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from treasurypilot_api.identity.oidc import (
    OIDCFailure,
    OIDCState,
    decode_state,
    encode_state,
    verify_id_token,
)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


_MISSING = object()


def _token(
    *,
    nonce: str = "expected",
    audience: str = "client",
    algorithm: str = "RS256",
    exp: int = 200,
    groups: object = ("finance",),
) -> tuple[str, dict[str, object]]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public = key.public_key().public_numbers()
    jwks: dict[str, object] = {
        "keys": [
            {
                "kid": "key-1",
                "kty": "RSA",
                "use": "sig",
                "n": _b64(public.n.to_bytes((public.n.bit_length() + 7) // 8, "big")),
                "e": _b64(public.e.to_bytes((public.e.bit_length() + 7) // 8, "big")),
            }
        ]
    }
    header = _b64(json.dumps({"alg": algorithm, "kid": "key-1"}, separators=(",", ":")).encode())
    claims: dict[str, object] = {
        "iss": "https://id.example",
        "aud": audience,
        "sub": "subject-1",
        "iat": 100,
        "exp": exp,
        "nonce": nonce,
        "email": "person@example.com",
        "email_verified": True,
        "name": "Person",
    }
    if groups is not _MISSING:
        claims["groups"] = groups
    payload = _b64(json.dumps(claims, separators=(",", ":")).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{payload}.{_b64(signature)}", jwks


def test_oidc_state_is_signed_bound_to_query_and_expires() -> None:
    state = OIDCState("state", "nonce", "verifier", 100)
    secret = b"s" * 32
    cookie = encode_state(state, secret)
    assert decode_state(cookie, "state", secret, now=200) == state
    with pytest.raises(OIDCFailure):
        decode_state(cookie, "other", secret, now=200)
    with pytest.raises(OIDCFailure):
        decode_state(cookie[:-1] + ("A" if cookie[-1] != "A" else "B"), "state", secret, now=200)
    with pytest.raises(OIDCFailure):
        decode_state(cookie, "state", secret, now=701)


def test_oidc_id_token_requires_signature_issuer_audience_nonce_and_verified_email() -> None:
    token, jwks = _token()
    claims = verify_id_token(
        token, jwks=jwks, issuer="https://id.example", audience="client", nonce="expected", now=150
    )
    assert claims.email == "person@example.com"
    assert claims.groups == ("finance",)
    for kwargs in ({"audience": "other"}, {"nonce": "other"}):
        bad_token, bad_jwks = _token(**kwargs)
        with pytest.raises(OIDCFailure):
            verify_id_token(
                bad_token,
                jwks=bad_jwks,
                issuer="https://id.example",
                audience="client",
                nonce="expected",
                now=150,
            )
    unsigned, _ = _token(algorithm="none")
    with pytest.raises(OIDCFailure):
        verify_id_token(
            unsigned,
            jwks=jwks,
            issuer="https://id.example",
            audience="client",
            nonce="expected",
            now=150,
        )


def test_oidc_client_uses_code_pkce_and_forces_a_fresh_provider_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import parse_qs, urlparse

    from treasurypilot_api.identity import oidc

    calls: list[tuple[str, bytes | None, dict[str, str] | None]] = []
    id_token, jwks = _token(nonce="nonce-value", exp=2_000_000_000)

    async def fake_fetch(
        url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
    ) -> dict[str, object]:
        calls.append((url, data, headers))
        if url.endswith("/.well-known/openid-configuration"):
            issuer = url.removesuffix("/.well-known/openid-configuration")
            return {
                "issuer": issuer,
                "authorization_endpoint": "https://id.example/authorize",
                "token_endpoint": "https://id.example/token",
                "jwks_uri": "https://id.example/jwks",
            }
        if url.endswith("/token"):
            return {"id_token": id_token}
        return jwks

    monkeypatch.setattr(oidc, "_fetch_json", fake_fetch)
    client = oidc.OIDCClient(
        issuer="https://id.example",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://app.example/v1/auth/oidc/callback",
    )
    state = OIDCState("state-value", "nonce-value", "long-verifier", 100)
    location = asyncio.run(client.authorization_url(state=state))
    query = parse_qs(urlparse(location).query)
    assert query["response_type"] == ["code"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["prompt"] == ["login"]
    assert query["max_age"] == ["0"]
    assert query["state"] == [state.state]
    assert calls[0][0] == "https://id.example/.well-known/openid-configuration"
    path_client = oidc.OIDCClient(
        issuer="https://id.example/oauth2/default",
        client_id="client",
        client_secret="secret",
        redirect_uri="https://app.example/v1/auth/oidc/callback",
    )
    asyncio.run(path_client.authorization_url(state=state))
    assert calls[-1][0] == "https://id.example/oauth2/default/.well-known/openid-configuration"
    claims = asyncio.run(client.exchange(code="authorization-code", state=state))
    assert claims.subject == "subject-1"
    token_request = next(call for call in calls if call[0].endswith("/token"))
    assert b"code_verifier=long-verifier" in (token_request[1] or b"")


def test_oidc_session_is_limited_to_five_minutes() -> None:
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from treasurypilot_api.identity.auth import AuthService, SessionTokenCodec, UserRecord
    from treasurypilot_api.identity.rate_limit import MemoryRateLimiter

    class Repository:
        created: dict[str, object]

        def __init__(self) -> None:
            self.created = {}

        async def create_session(self, **kwargs: object) -> None:
            self.created = kwargs

    class Sender:
        async def send_magic_link(self, **kwargs: object) -> None:
            return None

    now = datetime(2026, 10, 14, tzinfo=UTC)
    repository = Repository()
    organization_id = uuid4()
    service = AuthService(
        repository=repository,  # type: ignore[arg-type]
        sender=Sender(),
        token_codec=SessionTokenCodec(b"s" * 32),
        client_hash_secret=b"h" * 32,
        magic_link_base_url="https://app.example/verify",
        rate_limiter=MemoryRateLimiter(lambda: now),
        clock=lambda: now,
    )
    asyncio.run(
        service.create_oidc_session(
            user=UserRecord(uuid4(), "person@example.com", "Person", "active"),
            organization_id=organization_id,
            client_ip="127.0.0.1",
            user_agent="test",
        )
    )
    assert repository.created["expires_at"] - repository.created["created_at"] == timedelta(
        minutes=5
    )  # type: ignore[operator]
    assert repository.created["organization_scope_id"] == organization_id


def test_oidc_groups_claim_missing_is_none_and_malformed_is_rejected() -> None:
    def verify(groups: object) -> object:
        token, jwks = _token(groups=groups)
        return verify_id_token(
            token,
            jwks=jwks,
            issuer="https://id.example",
            audience="client",
            nonce="expected",
            now=150,
        )

    assert verify(_MISSING).groups is None  # type: ignore[attr-defined]
    assert verify([]).groups == ()  # type: ignore[attr-defined]
    for malformed in ("finance", {"a": 1}, ["finance", 7], 5):
        with pytest.raises(OIDCFailure):
            verify(malformed)


def test_oidc_discovery_endpoints_must_be_https_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from treasurypilot_api.identity import oidc

    async def fake_fetch(url: str, **_kwargs: object) -> dict[str, object]:
        return {
            "issuer": "https://id.example",
            "authorization_endpoint": "https://id.example/authorize",
            "token_endpoint": "http://127.0.0.1:8080/token",
            "jwks_uri": "https://id.example/jwks",
        }

    monkeypatch.setattr(oidc, "_fetch_json", fake_fetch)
    kwargs = {
        "issuer": "https://id.example",
        "client_id": "client",
        "client_secret": "secret",
        "redirect_uri": "https://app.example/cb",
    }
    state = OIDCState("s", "n", "v", 100)
    with pytest.raises(OIDCFailure):
        asyncio.run(oidc.OIDCClient(**kwargs).authorization_url(state=state))
    asyncio.run(oidc.OIDCClient(**kwargs, allow_local_http=True).authorization_url(state=state))


def test_oidc_fetch_wraps_http_protocol_errors_and_bad_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import http.client
    import urllib.request

    from treasurypilot_api.identity import oidc

    def broken(*_args: object, **_kwargs: object) -> object:
        raise http.client.IncompleteRead(b"")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", broken)
    with pytest.raises(OIDCFailure):
        asyncio.run(oidc._fetch_json("https://id.example/jwks"))

    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return b"[" * 100_000

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", lambda *_a, **_k: Response())
    with pytest.raises(OIDCFailure):
        asyncio.run(oidc._fetch_json("https://id.example/jwks"))
