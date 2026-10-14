from __future__ import annotations

import asyncio
import hashlib
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI, Request, Response
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import problem_response
from treasurypilot_api.identity.auth import (
    AuthFailure,
    AuthRepository,
    AuthService,
    MagicLinkSender,
    SessionTokenCodec,
)
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rate_limit import MemoryRateLimiter
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices.api_keys import CREATE_SCOPE, require_invoice_create
from treasurypilot_api.invoices.models import InvoiceApiKey
from treasurypilot_api.invoices.requests import router as request_router

API_ROOT = Path(__file__).parents[1]
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000917")
_USER = uuid.UUID("00000000-0000-7000-8000-000000000918")


class _Clock:
    def __call__(self) -> datetime:
        return datetime.now(UTC)


class _Members:
    async def member_roles(self, **_: object) -> frozenset[str]:
        return frozenset({"OrgAdmin"})


@pytest.fixture(scope="module")
def database_sessions() -> Iterator[async_sessionmaker[AsyncSession]]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for invoice API key integration tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")

    async def seed() -> None:
        engine = create_async_engine(url)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": _USER, "email": "invoice-api-key@example.test"},
                )
                await connection.execute(
                    text("INSERT INTO organizations (id, name) VALUES (:id, :name)"),
                    {"id": _ORG, "name": "Invoice API key integration"},
                )
        finally:
            await engine.dispose()

    asyncio.run(seed())
    engine = create_async_engine(url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:

        async def cleanup() -> None:
            async with engine.begin() as connection:
                await connection.execute(
                    text("DELETE FROM invoice_api_keys WHERE org_id = :org"), {"org": _ORG}
                )
                await connection.execute(
                    text("DELETE FROM organizations WHERE id = :org"), {"org": _ORG}
                )
                await connection.execute(
                    text("DELETE FROM users WHERE id = :user"), {"user": _USER}
                )

        asyncio.run(cleanup())
        asyncio.run(engine.dispose())
        command.downgrade(config, "base")


def test_api_key_scope_and_approval_boundary_with_postgres(
    database_sessions: async_sessionmaker[AsyncSession],
) -> None:
    valid_secret = "tp_live_integration_create"
    invalid_scope_secret = "tp_live_integration_approve"

    async def insert_keys() -> None:
        async with database_sessions() as session, session.begin():
            session.add_all(
                [
                    InvoiceApiKey(
                        id=uuid7(),
                        org_id=_ORG,
                        name="AP create",
                        prefix=valid_secret[:16],
                        token_hash=hashlib.sha256(valid_secret.encode()).digest(),
                        scopes=[CREATE_SCOPE],
                        created_by=_USER,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    ),
                    InvoiceApiKey(
                        id=uuid7(),
                        org_id=_ORG,
                        name="Invalid approval grant",
                        prefix=invalid_scope_secret[:16],
                        token_hash=hashlib.sha256(invalid_scope_secret.encode()).digest(),
                        scopes=["invoices:approve"],
                        created_by=_USER,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    ),
                ]
            )

    asyncio.run(insert_keys())
    limiter = MemoryRateLimiter(_Clock())
    key_request = cast(
        Request,
        SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    request_sessions=database_sessions,
                    api_key_rate_limiter=limiter,
                    organization_repository=_Members(),
                )
            )
        ),
    )
    valid = asyncio.run(
        require_invoice_create(
            _ORG,
            key_request,
            authorization=f"Bearer {valid_secret}",
        )
    )
    assert valid.organization_id == _ORG
    assert valid.api_key_id is not None

    with pytest.raises(AuthFailure) as error:
        asyncio.run(
            require_invoice_create(
                _ORG,
                key_request,
                authorization=f"Bearer {invalid_scope_secret}",
            )
        )
    assert error.value.code == "API_KEY_SCOPE_REQUIRED"

    app = FastAPI()
    app.state.settings = Settings()
    app.state.request_sessions = database_sessions
    app.state.auth_service = AuthService(
        repository=cast(AuthRepository, object()),
        sender=cast(MagicLinkSender, object()),
        token_codec=SessionTokenCodec(b"s" * 32),
        client_hash_secret=b"c" * 32,
        magic_link_base_url="https://example.test/auth/verify",
        rate_limiter=limiter,
    )

    async def handle_auth_failure(request: Request, error: Exception) -> Response:
        assert isinstance(error, AuthFailure)
        return problem_response(request, error)

    app.add_exception_handler(AuthFailure, handle_auth_failure)
    app.include_router(request_router)

    @app.post("/v1/orgs/{organization_id}/test-approve")
    async def test_approve(
        member: MemberAccess = Depends(require_role(OrganizationRole.APPROVER)),  # noqa: B008
    ) -> Response:
        return Response(status_code=204)

    with TestClient(app) as client:
        response = client.post(
            f"/v1/orgs/{_ORG}/test-approve",
            headers={"Authorization": f"Bearer {valid_secret}"},
        )
    assert response.status_code == 401
