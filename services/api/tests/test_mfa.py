from __future__ import annotations

import base64
import hashlib
import json
import struct
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import Depends
from fastapi.testclient import TestClient

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import (
    AuthService,
    SessionAccess,
    SessionTokenCodec,
    UserRecord,
)
from treasurypilot_api.identity.mfa import (
    FactorRecord,
    MfaError,
    MfaService,
    hash_recovery_code,
    match_totp,
    totp_code,
    verify_assertion,
    verify_registration,
)
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.main import create_app
from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

ORG_ID = uuid.UUID("00000000-0000-4000-8000-000000000111")
USER = UserRecord(
    uuid.UUID("00000000-0000-4000-8000-000000000001"), "owner@example.test", None, "active"
)
ORIGIN = "https://app.example.test"
SECRET = b"deterministic-test-secret-value!"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


class MemoryStore:
    """Auth + MFA repositories over one dict of sessions, like the shared database."""

    def __init__(self) -> None:
        self.step_up: dict[uuid.UUID, datetime] = {}
        self.sessions: dict[uuid.UUID, bytes] = {}
        self.factors: list[FactorRecord] = []
        self.codes: dict[bytes, bool] = {}

    # AuthRepository (only what the routes use)
    async def create_session(
        self, *, session_id: uuid.UUID, token_hash: bytes, **_: object
    ) -> None:
        self.sessions[session_id] = token_hash

    async def access_session(
        self, *, session_id: uuid.UUID, token_hash: bytes, **_: object
    ) -> SessionAccess | None:
        if self.sessions.get(session_id) != token_hash:
            return None
        return SessionAccess(USER, session_id, None, self.step_up.get(session_id))

    # MfaRepository
    async def list_factors(self, user_id: uuid.UUID) -> list[FactorRecord]:
        return [f for f in self.factors if f.user_id == user_id]

    async def add_factor(self, factor: FactorRecord) -> bool:
        if factor.credential_id and any(
            f.credential_id == factor.credential_id for f in self.factors
        ):
            return False
        self.factors.append(factor)
        return True

    async def _update(self, factor_id: uuid.UUID, **changes: object) -> None:
        self.factors = [replace(f, **changes) if f.id == factor_id else f for f in self.factors]

    async def confirm_factor(self, *, factor_id: uuid.UUID, now: datetime) -> None:
        await self._update(factor_id, confirmed_at=now)

    async def delete_factor(self, *, user_id: uuid.UUID, factor_id: uuid.UUID) -> bool:
        before = len(self.factors)
        self.factors = [f for f in self.factors if f.id != factor_id]
        return len(self.factors) < before

    async def advance_totp_counter(self, *, factor_id: uuid.UUID, counter: int) -> bool:
        factor = next(f for f in self.factors if f.id == factor_id)
        if factor.last_counter is not None and factor.last_counter >= counter:
            return False
        await self._update(factor_id, last_counter=counter)
        return True

    async def advance_sign_count(self, *, factor_id: uuid.UUID, sign_count: int) -> bool:
        await self._update(factor_id, sign_count=sign_count)
        return True

    async def replace_recovery_codes(
        self, *, user_id: uuid.UUID, code_hashes: list[bytes], now: datetime
    ) -> None:
        self.codes = {digest: False for digest in code_hashes}

    async def count_recovery_codes(self, user_id: uuid.UUID) -> int:
        return sum(not used for used in self.codes.values())

    async def consume_recovery_code(
        self, *, user_id: uuid.UUID, code_hash: bytes, now: datetime
    ) -> bool:
        if self.codes.get(code_hash) is False:
            self.codes[code_hash] = True
            return True
        return False

    async def mark_step_up(self, *, session_id: uuid.UUID, now: datetime) -> None:
        self.step_up[session_id] = now


@dataclass
class Harness:
    client: TestClient
    store: MemoryStore
    clock: Clock
    session_id: uuid.UUID
    mfa: MfaService

    def post(self, path: str, body: object = None, *, origin: str = ORIGIN):  # type: ignore[no-untyped-def]
        return self.client.post(
            path,
            json=body,
            headers={"X-CSRF-Token": self.client.cookies["tp_csrf"], "Origin": origin},
        )


def make_harness() -> Harness:
    clock = Clock()
    store = MemoryStore()
    limiter = MemoryRateLimiter(clock)
    codec = SessionTokenCodec(SECRET)
    auth = AuthService(
        repository=store,  # type: ignore[arg-type]
        sender=None,  # type: ignore[arg-type]
        token_codec=codec,
        client_hash_secret=SECRET,
        magic_link_base_url="https://app.example.test/auth/verify",
        rate_limiter=limiter,
        clock=clock,
    )
    mfa = MfaService(
        repository=store,
        cipher=FieldCipher(FieldEncryptionKey.from_base64(base64.b64encode(b"k" * 32).decode())),
        secret=SECRET,
        rate_limiter=limiter,
        clock=clock,
    )
    app = create_app(
        settings=Settings(environment="test", session_secret=SECRET.decode(), cors_origins=ORIGIN),
        auth_service=auth,
        rate_limiter=limiter,
        mfa_service=mfa,
    )

    async def membership(*, organization_id: uuid.UUID, user_id: uuid.UUID) -> frozenset[str]:
        return frozenset({"Owner", "Approver"})

    app.state.organization_repository = type(
        "Org", (), {"member_roles": staticmethod(membership)}
    )()

    # A stand-in for approve/exception/mandate routes, which use the same dependency.
    @app.post("/v1/orgs/{organization_id}/probe")
    async def probe(  # type: ignore[no-untyped-def]
        member: MemberAccess = Depends(require_role(OrganizationRole.OWNER, step_up=True)),  # noqa: B008
    ):
        return {"ok": True}

    session_id = uuid.uuid4()
    token = codec.session_token(session_id)
    import asyncio

    asyncio.run(
        store.create_session(
            session_id=session_id, token_hash=hashlib.sha256(token.encode()).digest()
        )
    )
    client = TestClient(app, base_url=ORIGIN)
    client.cookies.set("tp_session", token)
    client.cookies.set("tp_csrf", codec.csrf_token(session_id))
    return Harness(client, store, clock, session_id, mfa)


def enrol_totp(h: Harness) -> tuple[bytes, list[str]]:
    started = h.post("/v1/me/mfa/totp", {"label": "Phone"})
    assert started.status_code == 201
    factor = h.store.factors[0]
    secret = base64.b32decode(
        h.mfa._cipher.decrypt_text(factor.secret, context="mfa_factors.secret")
    )  # type: ignore[union-attr,arg-type]
    code = totp_code(secret, int(h.clock.now.timestamp()) // 30)
    confirmed = h.post(f"/v1/me/mfa/totp/{started.json()['factorId']}/confirm", {"code": code})
    assert confirmed.status_code == 200, confirmed.text
    return secret, confirmed.json()["recoveryCodes"]


# --- TOTP ------------------------------------------------------------------------------------


def test_totp_matches_rfc6238_vector() -> None:
    # RFC 6238 appendix B: SHA-1, secret "12345678901234567890", T=59 -> 94287082 (6 digits: 287082)
    assert totp_code(b"12345678901234567890", 59 // 30) == "287082"
    assert match_totp(b"12345678901234567890", "287082", datetime.fromtimestamp(59, UTC)) == 1
    assert match_totp(b"12345678901234567890", "287082", datetime.fromtimestamp(200, UTC)) is None


# --- Step-up on sensitive routes -------------------------------------------------------------


def test_sensitive_route_rejects_session_without_second_factor() -> None:
    h = make_harness()
    response = h.post(f"/v1/orgs/{ORG_ID}/probe")
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"


@pytest.mark.parametrize(
    "path",
    [
        "requests/00000000-0000-4000-8000-0000000000aa/approve",
        "treasuries/00000000-0000-4000-8000-0000000000bb/governance-txs",
        "treasuries/00000000-0000-4000-8000-0000000000bb/module/deploy-tx",
        "treasuries/00000000-0000-4000-8000-0000000000bb/mandates",
        "treasuries/00000000-0000-4000-8000-0000000000bb/mandates/00000000-0000-4000-8000-0000000000cc/clone",
    ],
)
def test_real_sensitive_routes_reject_missing_second_factor(path: str) -> None:
    h = make_harness()
    response = h.post(f"/v1/orgs/{ORG_ID}/{path}", {})
    assert response.status_code == 403
    assert response.json()["code"] == "STEP_UP_REQUIRED"


def test_totp_enrolment_steps_up_session_then_expires() -> None:
    h = make_harness()
    _, codes = enrol_totp(h)
    assert len(codes) == 10
    assert h.post(f"/v1/orgs/{ORG_ID}/probe").status_code == 200

    h.clock.now += timedelta(minutes=10)
    stale = h.post(f"/v1/orgs/{ORG_ID}/probe")
    assert stale.status_code == 403
    assert stale.json()["code"] == "STEP_UP_REQUIRED"


def test_step_up_with_totp_rejects_replay_and_wrong_code() -> None:
    h = make_harness()
    secret, _ = enrol_totp(h)
    h.clock.now += timedelta(minutes=11)
    assert h.post("/v1/me/mfa/step-up", {"code": "000000"}).json()["code"] == "MFA_CODE_INVALID"
    code = totp_code(secret, int(h.clock.now.timestamp()) // 30)
    assert h.post("/v1/me/mfa/step-up", {"code": code}).status_code == 204
    assert h.post(f"/v1/orgs/{ORG_ID}/probe").status_code == 200
    # The same code cannot be used twice.
    h.clock.now += timedelta(minutes=11)
    assert h.post("/v1/me/mfa/step-up", {"code": code}).status_code == 400
    assert h.post(f"/v1/orgs/{ORG_ID}/probe").status_code == 403


def test_recovery_code_is_single_use() -> None:
    h = make_harness()
    _, codes = enrol_totp(h)
    h.clock.now += timedelta(minutes=11)
    assert h.post("/v1/me/mfa/step-up", {"recoveryCode": codes[0]}).status_code == 204
    h.clock.now += timedelta(minutes=11)
    assert h.post("/v1/me/mfa/step-up", {"recoveryCode": codes[0]}).status_code == 400
    assert hash_recovery_code(codes[0].upper()) == hash_recovery_code(codes[0].replace("-", ""))
    assert h.client.get("/v1/me/mfa").json()["recoveryCodesRemaining"] == 9


def test_step_up_attempts_are_rate_limited() -> None:
    h = make_harness()
    enrol_totp(h)
    statuses = [h.post("/v1/me/mfa/step-up", {"code": "000000"}).status_code for _ in range(20)]
    assert 429 in statuses


def test_changing_factors_needs_fresh_step_up_once_enrolled() -> None:
    h = make_harness()
    enrol_totp(h)
    factor_id = h.store.factors[0].id
    h.clock.now += timedelta(minutes=11)
    assert h.post("/v1/me/mfa/totp", {"label": "Second"}).json()["code"] == "STEP_UP_REQUIRED"
    assert h.post("/v1/me/mfa/recovery-codes").status_code == 403
    assert (
        h.client.delete(
            f"/v1/me/mfa/{factor_id}", headers={"X-CSRF-Token": h.client.cookies["tp_csrf"]}
        ).status_code
        == 403
    )


def test_mfa_routes_require_authentication() -> None:
    h = make_harness()
    h.client.cookies.clear()
    assert h.client.get("/v1/me/mfa").status_code == 401


# --- WebAuthn --------------------------------------------------------------------------------


def _cbor(value: object) -> bytes:
    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        if n < 256:
            return bytes([major << 5 | 24, n])
        return bytes([major << 5 | 25]) + struct.pack(">H", n)

    if isinstance(value, bool) or value is None:
        raise AssertionError
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        return head(3, len(value.encode())) + value.encode()
    assert isinstance(value, dict)
    return head(5, len(value)) + b"".join(_cbor(k) + _cbor(v) for k, v in value.items())


def _b64u(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class Authenticator:
    """A software ES256 authenticator that produces what a browser would hand to the server."""

    def __init__(self, rp_id: str = "app.example.test") -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.rp_hash = hashlib.sha256(rp_id.encode()).digest()
        self.credential_id = b"credential-0001"
        self.counter = 0

    def attestation(self, challenge: str, *, origin: str = ORIGIN) -> tuple[bytes, bytes]:
        point = self.key.public_key().public_numbers()
        cose = {
            1: 2,
            3: -7,
            -1: 1,
            -2: point.x.to_bytes(32, "big"),
            -3: point.y.to_bytes(32, "big"),
        }
        auth_data = (
            self.rp_hash
            + bytes([0x45])
            + struct.pack(">I", 0)
            + b"\x00" * 16
            + struct.pack(">H", len(self.credential_id))
            + self.credential_id
            + _cbor(cose)
        )
        client = json.dumps({"type": "webauthn.create", "challenge": challenge, "origin": origin})
        return client.encode(), _cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})

    def assertion(
        self, challenge: str, *, origin: str = ORIGIN, bump: bool = True
    ) -> dict[str, bytes]:
        if bump:
            self.counter += 1
        auth_data = self.rp_hash + bytes([0x05]) + struct.pack(">I", self.counter)
        client = json.dumps(
            {"type": "webauthn.get", "challenge": challenge, "origin": origin}
        ).encode()
        signature = self.key.sign(
            auth_data + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "credential_id": self.credential_id,
            "client_data_json": client,
            "authenticator_data": auth_data,
            "signature": signature,
        }


def _assertion_body(a: dict[str, bytes]) -> dict[str, str]:
    return {
        "credentialId": _b64u(a["credential_id"]),
        "clientDataJson": _b64u(a["client_data_json"]),
        "authenticatorData": _b64u(a["authenticator_data"]),
        "signature": _b64u(a["signature"]),
    }


def register_key(h: Harness, authenticator: Authenticator) -> dict:  # type: ignore[type-arg]
    challenge = h.post("/v1/me/mfa/webauthn/challenge", {"purpose": "register"}).json()
    assert challenge["rpId"] == "app.example.test"
    client_data, attestation = authenticator.attestation(challenge["challenge"])
    response = h.post(
        "/v1/me/mfa/webauthn",
        {
            "label": "YubiKey",
            "clientDataJson": _b64u(client_data),
            "attestationObject": _b64u(attestation),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def test_webauthn_enrol_and_step_up() -> None:
    h = make_harness()
    authenticator = Authenticator()
    assert len(register_key(h, authenticator)["recoveryCodes"]) == 10

    challenge = h.post("/v1/me/mfa/webauthn/challenge", {"purpose": "assert"}).json()
    assert challenge["allowCredentials"] == [_b64u(authenticator.credential_id)]
    response = h.post(
        "/v1/me/mfa/step-up",
        {"webauthn": _assertion_body(authenticator.assertion(challenge["challenge"]))},
    )
    assert response.status_code == 204, response.text
    assert h.post(f"/v1/orgs/{ORG_ID}/probe").status_code == 200


def test_webauthn_rejects_replayed_counter_and_foreign_signature() -> None:
    h = make_harness()
    authenticator = Authenticator()
    register_key(h, authenticator)
    h.clock.now += timedelta(minutes=11)
    challenge = h.post("/v1/me/mfa/webauthn/challenge", {"purpose": "assert"}).json()["challenge"]
    first = authenticator.assertion(challenge)
    assert h.post("/v1/me/mfa/step-up", {"webauthn": _assertion_body(first)}).status_code == 204
    # Same assertion again: the signature counter did not advance.
    assert h.post("/v1/me/mfa/step-up", {"webauthn": _assertion_body(first)}).status_code == 400
    # A different key signing for the same credential id fails verification.
    forged = Authenticator()
    forged.counter = 50
    assert (
        h.post("/v1/me/mfa/step-up", {"webauthn": _assertion_body(forged.assertion(challenge))})
    ).status_code == 400


def test_webauthn_challenge_is_bound_to_purpose_and_origin() -> None:
    h = make_harness()
    authenticator = Authenticator()
    # A challenge issued for assertion cannot register a credential.
    wrong = h.post("/v1/me/mfa/webauthn/challenge", {"purpose": "assert"}).json()["challenge"]
    client_data, attestation = authenticator.attestation(wrong)
    assert (
        h.post(
            "/v1/me/mfa/webauthn",
            {"clientDataJson": _b64u(client_data), "attestationObject": _b64u(attestation)},
        ).json()["code"]
        == "MFA_REGISTRATION_INVALID"
    )
    # Unknown web origins are refused outright.
    assert (
        h.post("/v1/me/mfa/webauthn/challenge", {"purpose": "register"}, origin="https://evil.test")
    ).json()["code"] == "MFA_ORIGIN_INVALID"


def test_webauthn_parsers_reject_wrong_relying_party_and_origin() -> None:
    authenticator = Authenticator()
    client_data, attestation = authenticator.attestation("c")
    with pytest.raises(MfaError):
        verify_registration(
            rp_id="evil.test",
            origin=ORIGIN,
            client_data_json=client_data,
            attestation_object=attestation,
        )
    with pytest.raises(MfaError):
        verify_registration(
            rp_id="app.example.test",
            origin="https://evil.test",
            client_data_json=client_data,
            attestation_object=attestation,
        )
    credential = verify_registration(
        rp_id="app.example.test",
        origin=ORIGIN,
        client_data_json=client_data,
        attestation_object=attestation,
    )
    assertion = authenticator.assertion("c")
    with pytest.raises(MfaError):
        verify_assertion(
            rp_id="app.example.test",
            origin=ORIGIN,
            public_key=credential.public_key,
            client_data_json=assertion["client_data_json"],
            authenticator_data=assertion["authenticator_data"],
            signature=assertion["signature"][:-1] + b"\x00",
        )
