from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

OIDC_STATE_LIFETIME_SECONDS = 600


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _https_or_local(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme == "https" or (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    )


class OIDCFailure(Exception):
    """An identity provider response that cannot be trusted or used."""


@dataclass(frozen=True, slots=True)
class OIDCClaims:
    subject: str
    email: str
    display_name: str | None
    groups: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OIDCState:
    state: str
    nonce: str
    verifier: str
    issued_at: int


def encode_state(value: OIDCState, secret: bytes) -> str:
    payload = json.dumps(
        {"s": value.state, "n": value.nonce, "v": value.verifier, "iat": value.issued_at},
        separators=(",", ":"),
    ).encode()
    signature = hmac.digest(secret, b"treasurypilot/oidc-state/v1\x00" + payload, "sha256")
    return f"{_b64url(payload)}.{_b64url(signature)}"


def decode_state(
    cookie: str | None, state: str | None, secret: bytes, *, now: int | None = None
) -> OIDCState:
    try:
        payload_part, signature_part = (cookie or "").split(".", 1)
        payload = _unb64url(payload_part)
        signature = _unb64url(signature_part)
        expected = hmac.digest(secret, b"treasurypilot/oidc-state/v1\x00" + payload, "sha256")
        data = json.loads(payload)
        current_time = int(time.time()) if now is None else now
        if not hmac.compare_digest(signature, expected):
            raise ValueError
        if not hmac.compare_digest(str(data["s"]), state or ""):
            raise ValueError
        if (
            int(data["iat"]) > current_time
            or current_time - int(data["iat"]) > OIDC_STATE_LIFETIME_SECONDS
        ):
            raise ValueError
        return OIDCState(str(data["s"]), str(data["n"]), str(data["v"]), int(data["iat"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise OIDCFailure("invalid or expired OIDC state") from None


def verify_id_token(
    token: str,
    *,
    jwks: dict[str, Any],
    issuer: str,
    audience: str,
    nonce: str,
    now: int | None = None,
) -> OIDCClaims:
    """Verify an RS256 OIDC ID token with a provider JWKS and strict OIDC claims."""
    try:
        encoded_header, encoded_payload, encoded_signature = token.split(".")
        header = json.loads(_unb64url(encoded_header))
        claims = json.loads(_unb64url(encoded_payload))
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise ValueError
        keys = [key for key in jwks.get("keys", []) if key.get("kid") == header["kid"]]
        if len(keys) != 1 or keys[0].get("kty") != "RSA" or keys[0].get("use", "sig") != "sig":
            raise ValueError
        key = keys[0]
        public_key = rsa.RSAPublicNumbers(
            int.from_bytes(_unb64url(key["e"]), "big"), int.from_bytes(_unb64url(key["n"]), "big")
        ).public_key()
        if public_key.key_size < 2048:
            raise ValueError
        public_key.verify(
            _unb64url(encoded_signature),
            f"{encoded_header}.{encoded_payload}".encode("ascii"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        now_value = int(time.time()) if now is None else now
        exp = int(claims["exp"])
        iat = int(claims["iat"])
        aud = claims["aud"]
        if isinstance(aud, list):
            if any(not isinstance(item, str) for item in aud) or audience not in aud:
                raise ValueError
        elif not isinstance(aud, str) or aud != audience:
            raise ValueError
        if claims.get("iss") != issuer:
            raise ValueError
        if isinstance(aud, list) and claims.get("azp") != audience:
            raise ValueError
        token_nonce = claims.get("nonce")
        not_before = int(claims.get("nbf", 0))
        if (
            exp <= now_value
            or not_before > now_value + 60
            or iat > now_value + 60
            or not isinstance(token_nonce, str)
            or not hmac.compare_digest(token_nonce, nonce)
        ):
            raise ValueError
        if claims.get("email_verified") is not True:
            raise ValueError
        subject, email = claims.get("sub"), claims.get("email")
        if (
            not isinstance(subject, str)
            or not subject
            or len(subject) > 255
            or not isinstance(email, str)
            or not 3 <= len(email) <= 320
            or "@" not in email
        ):
            raise ValueError
        groups = claims.get("groups", [])
        if not isinstance(groups, list) or any(not isinstance(group, str) for group in groups):
            groups = []
        name = claims.get("name")
        return OIDCClaims(
            subject, email.strip().lower(), name if isinstance(name, str) else None, tuple(groups)
        )
    except Exception as exc:
        if isinstance(exc, OIDCFailure):
            raise
        raise OIDCFailure("invalid OIDC ID token") from None


async def _fetch_json(
    url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    if not _https_or_local(url):
        raise OIDCFailure("OIDC endpoints must use HTTPS")

    def fetch() -> dict[str, Any]:
        request = urllib.request.Request(
            url, data=data, headers=headers or {}, method="POST" if data is not None else "GET"
        )

        class RejectRedirects(urllib.request.HTTPRedirectHandler):
            def redirect_request(
                self, req: Any, fp: Any, code: int, msg: str, hdrs: Any, newurl: str
            ) -> None:
                return None

        opener = urllib.request.build_opener(RejectRedirects())
        try:
            with opener.open(request, timeout=5) as response:
                if response.status != 200:
                    raise OIDCFailure("OIDC provider request failed")
                body = response.read(1_000_001)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise OIDCFailure("OIDC provider unavailable") from None
        if len(body) > 1_000_000:
            raise OIDCFailure("OIDC provider response too large")
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise OIDCFailure("invalid OIDC provider response") from None
        if not isinstance(parsed, dict):
            raise OIDCFailure("invalid OIDC provider response")
        return parsed

    return await asyncio.to_thread(fetch)


class OIDCClient:
    def __init__(
        self, *, issuer: str, client_id: str, client_secret: str, redirect_uri: str
    ) -> None:
        if not _https_or_local(issuer) or not _https_or_local(redirect_uri):
            raise ValueError("OIDC issuer and redirect URI must use HTTPS")
        self.issuer = issuer
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    async def authorization_url(self, *, state: OIDCState) -> str:
        metadata = await self._metadata()
        challenge = _b64url(hashlib.sha256(state.verifier.encode("ascii")).digest())
        query = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "scope": "openid email profile",
                "state": state.state,
                "nonce": state.nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "login",
                "max_age": "0",
            }
        )
        return f"{metadata['authorization_endpoint']}?{query}"

    async def exchange(self, *, code: str, state: OIDCState) -> OIDCClaims:
        metadata = await self._metadata()
        payload = urllib.parse.urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code_verifier": state.verifier,
            }
        ).encode()
        tokens = await _fetch_json(
            metadata["token_endpoint"],
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        token = tokens.get("id_token")
        if not isinstance(token, str):
            raise OIDCFailure("OIDC response did not include an ID token")
        jwks = await _fetch_json(metadata["jwks_uri"])
        return verify_id_token(
            token, jwks=jwks, issuer=self.issuer, audience=self.client_id, nonce=state.nonce
        )

    async def _metadata(self) -> dict[str, Any]:
        discovery_url = f"{self.issuer.rstrip('/')}/.well-known/openid-configuration"
        metadata = await _fetch_json(discovery_url)
        if metadata.get("issuer") != self.issuer:
            raise OIDCFailure("OIDC issuer does not match discovery metadata")
        for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not isinstance(metadata.get(key), str) or not _https_or_local(metadata[key]):
                raise OIDCFailure("invalid OIDC discovery metadata")
        return metadata


def new_state() -> OIDCState:
    return OIDCState(
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(32),
        secrets.token_urlsafe(64),
        int(time.time()),
    )
