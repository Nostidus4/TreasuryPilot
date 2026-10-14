"""Second factors (TOTP, WebAuthn, recovery codes) and the step-up check (IDN-L01, FR-016).

Only the standard library and ``cryptography`` are used: TOTP is RFC 6238 over ``hmac`` and
WebAuthn verifies ES256 assertions with "none" attestation.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import struct
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

from treasurypilot_api.identity.auth import (
    AuthFailure,
    hash_client_value,
    require_aware_utc,
    utc_now,
)
from treasurypilot_api.identity.rate_limit import RateLimiter, RateLimiterUnavailable
from treasurypilot_core.privacy import FieldCipher

TOTP_STEP = 30
TOTP_DIGITS = 6
CHALLENGE_LIFETIME = timedelta(minutes=5)
PENDING_FACTOR_LIFETIME = timedelta(minutes=10)
CBOR_MAX_DEPTH = 8
RECOVERY_CODE_COUNT = 10
# Brute force bound: 20 attempts x 3 accepted time steps / 10^6 codes per 15 minutes.
STEP_UP_ATTEMPT_LIMIT = 20
STEP_UP_ATTEMPT_WINDOW = timedelta(minutes=15)
SECRET_CONTEXT = "mfa_factors.secret"
_CHALLENGE_CONTEXT = b"treasurypilot/webauthn-challenge/v1\x00"

Purpose = Literal["register", "assert"]


class MfaError(Exception):
    """A second factor failed verification; the message is never shown to the client."""


def mfa_failure(
    status: int, code: str, detail: str, *, retry_after: int | None = None
) -> AuthFailure:
    return AuthFailure(
        status=status,
        code=code,
        title=code.replace("_", " ").capitalize(),
        detail=detail,
        retry_after=retry_after,
    )


# --- TOTP (RFC 6238, HMAC-SHA1, 6 digits, 30 s) -------------------------------------------


def new_totp_secret() -> bytes:
    return secrets.token_bytes(20)


def totp_code(secret: bytes, counter: int) -> str:
    digest = hmac.digest(secret, struct.pack(">Q", counter), "sha1")
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def match_totp(secret: bytes, code: str, now: datetime) -> int | None:
    """Return the matching time step within +-1 step of clock drift, or ``None``."""

    current = int(now.timestamp()) // TOTP_STEP
    matched: int | None = None
    for counter in (current - 1, current, current + 1):
        # Compare every candidate so timing does not reveal which step matched.
        if hmac.compare_digest(totp_code(secret, counter), code):
            matched = counter
    return matched


def totp_uri(secret: bytes, *, account: str, issuer: str = "TreasuryPilot") -> str:
    b32 = base64.b32encode(secret).decode().rstrip("=")
    label = quote(f"{issuer}:{account}", safe="")
    return f"otpauth://totp/{label}?secret={b32}&issuer={quote(issuer)}&digits={TOTP_DIGITS}"


# --- Recovery codes -------------------------------------------------------------------------


def new_recovery_codes() -> list[str]:
    """80 bits each, as four groups of five hex digits."""

    return [
        "-".join(raw[i : i + 5] for i in range(0, 20, 5))
        for raw in (secrets.token_hex(10) for _ in range(RECOVERY_CODE_COUNT))
    ]


def hash_recovery_code(code: str, secret: bytes) -> bytes:
    """Keyed so a leaked table cannot be brute forced without the server secret."""

    return hash_client_value(code.strip().lower().replace("-", ""), secret)


# --- WebAuthn -------------------------------------------------------------------------------


def b64u_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


def b64u_decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError:
        raise MfaError("bad base64") from None


def new_challenge(secret: bytes, purpose: Purpose, user_id: uuid.UUID, now: datetime) -> str:
    """Stateless challenge: nonce + expiry, MACed for one purpose and one user.

    shortcut: not single-use server side (a captured assertion replays until the 5 minute expiry
    or until the authenticator's signature counter moves past it), upgrade to stored nonces if
    authenticators without counters must be supported.
    """

    body = secrets.token_bytes(16) + struct.pack(
        ">Q", int(now.timestamp()) + int(CHALLENGE_LIFETIME.total_seconds())
    )
    return b64u_encode(body + _challenge_mac(secret, purpose, user_id, body))


def _challenge_mac(secret: bytes, purpose: str, user_id: uuid.UUID, body: bytes) -> bytes:
    message = _CHALLENGE_CONTEXT + purpose.encode() + b"\x00" + user_id.bytes + body
    return hmac.digest(secret, message, "sha256")


def check_challenge(
    secret: bytes, purpose: Purpose, user_id: uuid.UUID, challenge: str, now: datetime
) -> bool:
    try:
        raw = b64u_decode(challenge)
    except MfaError:
        return False
    if len(raw) != 56:
        return False
    body, mac = raw[:24], raw[24:]
    expiry = struct.unpack(">Q", body[16:])[0]
    return hmac.compare_digest(mac, _challenge_mac(secret, purpose, user_id, body)) and (
        int(now.timestamp()) < expiry
    )


def _cbor(data: bytes, i: int = 0) -> tuple[Any, int]:
    """Decode the CBOR subset WebAuthn uses: ints, bytes, text, arrays, maps, simple values."""

    try:
        return _cbor_item(data, i, 0)
    except (RecursionError, TypeError):  # TypeError: unhashable map key
        raise MfaError("bad CBOR") from None


def _cbor_item(data: bytes, i: int, depth: int) -> tuple[Any, int]:
    if depth > CBOR_MAX_DEPTH:
        raise MfaError("CBOR too deep")
    if i >= len(data):
        raise MfaError("truncated CBOR")
    major, info = data[i] >> 5, data[i] & 0x1F
    i += 1
    if info < 24:
        arg = info
    elif info in (24, 25, 26, 27):
        size = 1 << (info - 24)
        if i + size > len(data):
            raise MfaError("truncated CBOR")
        arg = int.from_bytes(data[i : i + size], "big")
        i += size
    else:
        raise MfaError("unsupported CBOR")
    if major == 0:
        return arg, i
    if major == 1:
        return -1 - arg, i
    if major in (2, 3):
        if i + arg > len(data):
            raise MfaError("truncated CBOR")
        chunk = data[i : i + arg]
        return (chunk if major == 2 else chunk.decode("utf-8", "replace")), i + arg
    if major == 4:
        items = []
        for _ in range(arg):
            item, i = _cbor_item(data, i, depth + 1)
            items.append(item)
        return items, i
    if major == 5:
        mapping: dict[Any, Any] = {}
        for _ in range(arg):
            key, i = _cbor_item(data, i, depth + 1)
            mapping[key], i = _cbor_item(data, i, depth + 1)
        return mapping, i
    if major == 7 and info in (20, 21, 22):
        return {20: False, 21: True, 22: None}[info], i
    raise MfaError("unsupported CBOR")


def _client_data(raw: bytes, *, kind: str, origin: str) -> str:
    """Validate clientDataJSON and return the challenge it carries."""

    try:
        data = json.loads(raw)
    except ValueError:
        raise MfaError("bad clientDataJSON") from None
    if (
        not isinstance(data, dict)
        or data.get("type") != kind
        or data.get("origin") != origin
        or data.get("crossOrigin") is True
        or not isinstance(data.get("challenge"), str)
    ):
        raise MfaError("clientDataJSON mismatch")
    return str(data["challenge"])


def _check_auth_data(auth_data: bytes, rp_id: str) -> tuple[int, int]:
    """Return (flags, signCount); the RP id hash and user-presence bit must be right."""

    if len(auth_data) < 37 or not hmac.compare_digest(
        auth_data[:32], hashlib.sha256(rp_id.encode()).digest()
    ):
        raise MfaError("rpIdHash mismatch")
    flags = auth_data[32]
    if not flags & 0x01:
        raise MfaError("user presence missing")
    return flags, struct.unpack(">I", auth_data[33:37])[0]


@dataclass(frozen=True, slots=True)
class WebAuthnCredential:
    credential_id: bytes
    public_key: bytes  # raw x || y
    sign_count: int
    challenge: str


def verify_registration(
    *, rp_id: str, origin: str, client_data_json: bytes, attestation_object: bytes
) -> WebAuthnCredential:
    """Accept a ``none``-attestation ES256 credential; the caller checks the challenge."""

    challenge = _client_data(client_data_json, kind="webauthn.create", origin=origin)
    attestation, _ = _cbor(attestation_object)
    auth_data = attestation.get("authData") if isinstance(attestation, dict) else None
    if not isinstance(auth_data, bytes):
        raise MfaError("missing authData")
    flags, sign_count = _check_auth_data(auth_data, rp_id)
    if not flags & 0x40 or len(auth_data) < 55:
        raise MfaError("no attested credential")
    id_length = int.from_bytes(auth_data[53:55], "big")
    credential_id = auth_data[55 : 55 + id_length]
    if not credential_id or len(credential_id) != id_length:
        raise MfaError("bad credential id")
    cose, _ = _cbor(auth_data, 55 + id_length)
    if not isinstance(cose, dict) or (cose.get(1), cose.get(3), cose.get(-1)) != (2, -7, 1):
        raise MfaError("only ES256 credentials are supported")
    x, y = cose.get(-2), cose.get(-3)
    if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == len(y) == 32):
        raise MfaError("bad public key")
    _load_key(x + y)  # rejects points that are not on the curve
    return WebAuthnCredential(credential_id, x + y, sign_count, challenge)


def _load_key(xy: bytes) -> ec.EllipticCurvePublicKey:
    try:
        return ec.EllipticCurvePublicNumbers(
            int.from_bytes(xy[:32], "big"), int.from_bytes(xy[32:], "big"), ec.SECP256R1()
        ).public_key()
    except ValueError:
        raise MfaError("invalid public key") from None


def verify_assertion(
    *,
    rp_id: str,
    origin: str,
    public_key: bytes,
    client_data_json: bytes,
    authenticator_data: bytes,
    signature: bytes,
) -> tuple[str, int]:
    """Verify an ES256 assertion; return (challenge, signCount). The caller checks both."""

    challenge = _client_data(client_data_json, kind="webauthn.get", origin=origin)
    _, sign_count = _check_auth_data(authenticator_data, rp_id)
    signed = authenticator_data + hashlib.sha256(client_data_json).digest()
    try:
        _load_key(public_key).verify(signature, signed, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        raise MfaError("bad signature") from None
    return challenge, sign_count


# --- Service ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FactorRecord:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    label: str
    secret: str | None
    credential_id: bytes | None
    public_key: bytes | None
    sign_count: int
    last_counter: int | None
    created_at: datetime
    confirmed_at: datetime | None


class MfaRepository(Protocol):
    async def list_factors(self, user_id: uuid.UUID) -> list[FactorRecord]: ...

    async def add_factor(self, factor: FactorRecord) -> bool:
        """Insert; ``False`` when the WebAuthn credential id is already registered."""
        ...

    async def confirm_factor(self, *, factor_id: uuid.UUID, now: datetime) -> None: ...

    async def delete_pending_factors(self, *, user_id: uuid.UUID, before: datetime) -> None:
        """Drop unconfirmed factors created before ``before``."""
        ...

    async def delete_factor(self, *, user_id: uuid.UUID, factor_id: uuid.UUID) -> bool: ...

    async def advance_totp_counter(self, *, factor_id: uuid.UUID, counter: int) -> bool:
        """Atomically record ``counter``; ``False`` when it was already used."""
        ...

    async def advance_sign_count(self, *, factor_id: uuid.UUID, sign_count: int) -> bool: ...

    async def replace_recovery_codes(
        self, *, user_id: uuid.UUID, code_hashes: list[bytes], now: datetime
    ) -> None: ...

    async def count_recovery_codes(self, user_id: uuid.UUID) -> int: ...

    async def consume_recovery_code(
        self, *, user_id: uuid.UUID, code_hash: bytes, now: datetime
    ) -> bool: ...

    async def mark_step_up(self, *, session_id: uuid.UUID, now: datetime) -> None: ...


class MfaService:
    def __init__(
        self,
        *,
        repository: MfaRepository,
        cipher: FieldCipher | None,
        secret: bytes,
        rate_limiter: RateLimiter,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._secret = secret
        self._rate_limiter = rate_limiter
        self._clock = clock

    def _now(self) -> datetime:
        return require_aware_utc(self._clock())

    async def factors(self, user_id: uuid.UUID) -> list[FactorRecord]:
        return [f for f in await self._repository.list_factors(user_id) if f.confirmed_at]

    async def recovery_codes_remaining(self, user_id: uuid.UUID) -> int:
        return await self._repository.count_recovery_codes(user_id)

    async def start_totp(
        self, *, user_id: uuid.UUID, email: str, label: str
    ) -> tuple[FactorRecord, str]:
        if self._cipher is None:
            raise mfa_failure(503, "MFA_UNAVAILABLE", "Field encryption is not configured.")
        secret = new_totp_secret()
        factor = FactorRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            kind="totp",
            label=label,
            secret=self._cipher.encrypt_text(
                base64.b32encode(secret).decode(), context=SECRET_CONTEXT
            ),
            credential_id=None,
            public_key=None,
            sign_count=0,
            last_counter=None,
            created_at=self._now(),
            confirmed_at=None,
        )
        await self._repository.delete_pending_factors(
            user_id=user_id, before=self._now() - PENDING_FACTOR_LIFETIME
        )
        await self._repository.add_factor(factor)
        return factor, totp_uri(secret, account=email)

    def _totp_secret(self, factor: FactorRecord) -> bytes:
        if self._cipher is None or factor.secret is None:
            raise mfa_failure(503, "MFA_UNAVAILABLE", "Field encryption is not configured.")
        return base64.b32decode(self._cipher.decrypt_text(factor.secret, context=SECRET_CONTEXT))

    async def _first_factor_codes(self, user_id: uuid.UUID, had_factors: bool) -> list[str]:
        """Recovery codes are issued once, with the first confirmed factor."""

        return [] if had_factors else await self.regenerate_recovery_codes(user_id)

    async def confirm_totp(
        self, *, user_id: uuid.UUID, session_id: uuid.UUID, factor_id: uuid.UUID, code: str
    ) -> tuple[FactorRecord, list[str]]:
        await self._limit(user_id)
        existing = await self._repository.list_factors(user_id)
        factor = next((f for f in existing if f.id == factor_id and f.kind == "totp"), None)
        if (
            factor is None
            or factor.confirmed_at is not None
            or self._now() - factor.created_at > PENDING_FACTOR_LIFETIME
        ):
            raise mfa_failure(404, "MFA_FACTOR_NOT_FOUND", "No pending authenticator app.")
        counter = match_totp(self._totp_secret(factor), code, self._now())
        if counter is None or not await self._repository.advance_totp_counter(
            factor_id=factor.id, counter=counter
        ):
            raise mfa_failure(400, "MFA_CODE_INVALID", "The code is not valid.")
        had_factors = any(f.confirmed_at for f in existing)
        now = self._now()
        await self._repository.confirm_factor(factor_id=factor.id, now=now)
        # The code just proved possession of the factor, so this session is stepped up.
        await self._repository.mark_step_up(session_id=session_id, now=now)
        return factor, await self._first_factor_codes(user_id, had_factors)

    def challenge(self, purpose: Purpose, user_id: uuid.UUID) -> str:
        return new_challenge(self._secret, purpose, user_id, self._now())

    async def register_webauthn(
        self,
        *,
        user_id: uuid.UUID,
        label: str,
        rp_id: str,
        origin: str,
        client_data_json: bytes,
        attestation_object: bytes,
    ) -> tuple[FactorRecord, list[str]]:
        try:
            credential = verify_registration(
                rp_id=rp_id,
                origin=origin,
                client_data_json=client_data_json,
                attestation_object=attestation_object,
            )
            if not check_challenge(
                self._secret, "register", user_id, credential.challenge, self._now()
            ):
                raise MfaError("bad challenge")
        except MfaError:
            raise mfa_failure(
                400, "MFA_REGISTRATION_INVALID", "The security key was rejected."
            ) from None
        had_factors = bool(await self.factors(user_id))
        factor = FactorRecord(
            id=uuid.uuid4(),
            user_id=user_id,
            kind="webauthn",
            label=label,
            secret=None,
            credential_id=credential.credential_id,
            public_key=credential.public_key,
            sign_count=credential.sign_count,
            last_counter=None,
            created_at=self._now(),
            confirmed_at=self._now(),
        )
        if not await self._repository.add_factor(factor):
            raise mfa_failure(
                409, "MFA_CREDENTIAL_EXISTS", "This security key is already registered."
            )
        return factor, await self._first_factor_codes(user_id, had_factors)

    async def regenerate_recovery_codes(self, user_id: uuid.UUID) -> list[str]:
        codes = new_recovery_codes()
        await self._repository.replace_recovery_codes(
            user_id=user_id,
            code_hashes=[hash_recovery_code(code, self._secret) for code in codes],
            now=self._now(),
        )
        return codes

    async def delete_factor(self, *, user_id: uuid.UUID, factor_id: uuid.UUID) -> None:
        if not await self._repository.delete_factor(user_id=user_id, factor_id=factor_id):
            raise mfa_failure(404, "MFA_FACTOR_NOT_FOUND", "No such second factor.")

    async def _limit(self, user_id: uuid.UUID) -> None:
        try:
            result = await self._rate_limiter.hit(
                f"mfa:{user_id}", limit=STEP_UP_ATTEMPT_LIMIT, window=STEP_UP_ATTEMPT_WINDOW
            )
        except RateLimiterUnavailable:
            raise mfa_failure(
                503, "AUTH_UNAVAILABLE", "Try again shortly.", retry_after=30
            ) from None
        if not result.allowed:
            raise mfa_failure(
                429, "RATE_LIMITED", "Too many attempts.", retry_after=result.retry_after
            )

    async def step_up(
        self,
        *,
        user_id: uuid.UUID,
        session_id: uuid.UUID,
        code: str | None = None,
        recovery_code: str | None = None,
        assertion: dict[str, bytes] | None = None,
        rp_id: str = "",
        origin: str = "",
    ) -> None:
        """Verify one factor and stamp the session; raises ``MFA_CODE_INVALID`` otherwise."""

        await self._limit(user_id)
        now = self._now()
        factors = await self.factors(user_id)
        ok = False
        if code is not None:
            for factor in (f for f in factors if f.kind == "totp"):
                counter = match_totp(self._totp_secret(factor), code, now)
                if counter is not None and await self._repository.advance_totp_counter(
                    factor_id=factor.id, counter=counter
                ):
                    ok = True
        elif recovery_code is not None:
            ok = await self._repository.consume_recovery_code(
                user_id=user_id, code_hash=hash_recovery_code(recovery_code, self._secret), now=now
            )
        elif assertion is not None:
            ok = await self._verify_assertion(
                user_id, factors, assertion, rp_id=rp_id, origin=origin, now=now
            )
        if not ok:
            raise mfa_failure(400, "MFA_CODE_INVALID", "The second factor was not accepted.")
        await self._repository.mark_step_up(session_id=session_id, now=now)

    async def _verify_assertion(
        self,
        user_id: uuid.UUID,
        factors: list[FactorRecord],
        assertion: dict[str, bytes],
        *,
        rp_id: str,
        origin: str,
        now: datetime,
    ) -> bool:
        factor = next((f for f in factors if f.credential_id == assertion["credential_id"]), None)
        if factor is None or factor.public_key is None:
            return False
        try:
            challenge, sign_count = verify_assertion(
                rp_id=rp_id,
                origin=origin,
                public_key=factor.public_key,
                client_data_json=assertion["client_data_json"],
                authenticator_data=assertion["authenticator_data"],
                signature=assertion["signature"],
            )
        except MfaError:
            return False
        if not check_challenge(self._secret, "assert", user_id, challenge, now):
            return False
        if sign_count == 0 and factor.sign_count == 0:
            return True  # authenticator without a counter
        # A counter that does not advance means a cloned authenticator or a replay.
        return sign_count > factor.sign_count and await self._repository.advance_sign_count(
            factor_id=factor.id, sign_count=sign_count
        )
