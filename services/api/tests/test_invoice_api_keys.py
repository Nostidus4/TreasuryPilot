from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import uuid7
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices.api_keys import (
    CREATE_SCOPE,
    ApiKeyCreate,
    create_api_key,
    require_invoice_create,
)
from treasurypilot_api.invoices.models import InvoiceApiKey

_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")


class _Session:
    def __init__(self, key: InvoiceApiKey | None = None) -> None:
        self.key = key
        self.added: InvoiceApiKey | None = None
        self.committed = False

    async def __aenter__(self) -> _Session:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> _Session:
        return self

    def add(self, item: InvoiceApiKey) -> None:
        self.added = item

    async def flush(self) -> None:
        if self.added is not None and self.added.created_at is None:
            self.added.created_at = datetime.now(UTC)
        return None

    async def commit(self) -> None:
        self.committed = True

    async def scalar(self, _statement: object) -> InvoiceApiKey | None:
        return self.key


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self) -> _Session:
        return self.session


def _request(session: _Session) -> SimpleNamespace:
    state = SimpleNamespace(request_sessions=_SessionFactory(session))
    return SimpleNamespace(app=SimpleNamespace(state=state))


def _member() -> MemberAccess:
    return MemberAccess(
        access=SimpleNamespace(user=SimpleNamespace(id=_USER)),  # type: ignore[arg-type]
        organization_id=_ORG,
        roles=frozenset({"OrgAdmin"}),
    )


def test_api_key_create_returns_one_time_secret_and_stores_only_hash() -> None:
    session = _Session()
    request = _request(session)
    payload = ApiKeyCreate(name="AP sync", scopes=[CREATE_SCOPE])
    result = asyncio.run(create_api_key(_ORG, payload, request, _member()))

    raw = result["secret"]
    assert isinstance(raw, str) and raw.startswith("tp_live_")
    assert session.added is not None
    assert session.added.token_hash == hashlib.sha256(raw.encode()).digest()
    assert raw not in str(result["key"])
    assert result["key"]["scopes"] == [CREATE_SCOPE]
    assert session.committed is False  # transaction context owns commit


def test_api_key_creation_rejects_unapproved_scope() -> None:
    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            create_api_key(
                _ORG,
                ApiKeyCreate(name="key", scopes=["invoices:approve"]),
                _request(_Session()),
                _member(),
            )
        )
    assert error.value.code == "API_KEY_SCOPE_INVALID"


def test_api_key_auth_is_org_scoped_and_create_only() -> None:
    raw = "tp_live_secret"
    key = InvoiceApiKey(
        id=uuid7(), org_id=_ORG, name="AP", prefix=raw[:16],
        token_hash=hashlib.sha256(raw.encode()).digest(), scopes=[CREATE_SCOPE],
        created_by=_USER, expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    access = asyncio.run(
        require_invoice_create(
            _ORG,
            _request(_Session(key)),
            authorization=f"Bearer {raw}",
        )
    )
    assert access.api_key_id == key.id
    assert access.user_id == _USER

    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            require_invoice_create(
                uuid.uuid4(), _request(_Session(key)), authorization=f"Bearer {raw}"
            )
        )
    assert error.value.code == "API_KEY_ORG_MISMATCH"

    key.scopes = ["invoices:approve"]
    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            require_invoice_create(
                _ORG, _request(_Session(key)), authorization=f"Bearer {raw}"
            )
        )
    assert error.value.code == "API_KEY_SCOPE_REQUIRED"


def test_api_key_auth_rejects_expired_key() -> None:
    raw = "tp_live_expired"
    key = InvoiceApiKey(
        id=uuid7(), org_id=_ORG, name="AP", prefix=raw[:16],
        token_hash=hashlib.sha256(raw.encode()).digest(), scopes=[CREATE_SCOPE],
        created_by=_USER, expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            require_invoice_create(_ORG, _request(_Session(key)), authorization=f"Bearer {raw}")
        )
    assert error.value.code == "API_KEY_INVALID"
