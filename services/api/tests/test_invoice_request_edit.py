from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Response
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess
from treasurypilot_api.invoices.requests import (
    RequestCreate,
    RequestPatch,
    create_request,
    edit_request,
)
from treasurypilot_api.mandate.models import Payee  # noqa: F401  (registers mapper)

API_ROOT = Path(__file__).parents[1]
_USER = uuid.UUID("00000000-0000-7000-8000-000000000001")
_ORG = uuid.UUID("00000000-0000-7000-8000-000000000010")
_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000030")
_OTHER_ASSET = uuid.UUID("00000000-0000-7000-8000-000000000031")
_TREASURY = uuid.UUID("00000000-0000-7000-8000-000000000040")
_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000050")
_OTHER_VENDOR = uuid.UUID("00000000-0000-7000-8000-000000000051")
_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000060")
_OTHER_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000061")
_OTHER_VENDOR_PAYEE = uuid.UUID("00000000-0000-7000-8000-000000000062")
_MEMBER = MemberAccess(
    access=SimpleNamespace(user=SimpleNamespace(id=_USER)),  # type: ignore[arg-type]
    organization_id=_ORG,
    roles=frozenset({"OPERATOR"}),
)


def test_patch_rejects_explicit_null_for_required_fields() -> None:
    for name in ("invoice_no", "issue_date", "due_date", "amount", "payee_id", "tags"):
        with pytest.raises(ValidationError):
            RequestPatch.model_validate({name: None})
    assert RequestPatch.model_validate({"note": None, "terms": None}).note is None


async def _seed(database_url: str) -> None:
    engine = create_async_engine(database_url)
    statements = [
        f"INSERT INTO users (id, email) VALUES ('{_USER}', 'edit@example.com')",
        f"INSERT INTO organizations (id, name) VALUES ('{_ORG}', 'Edit test')",
        "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls) "
        "VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '[\"https://rpc\"]')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_ASSET}', 11155111, decode(repeat('11', 20), 'hex'), 'USDC', 6, 'Circle')",
        "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) "
        f"VALUES ('{_OTHER_ASSET}', 11155111, decode(repeat('44', 20), 'hex'), 'DAI', 18, 'Test')",
        "INSERT INTO treasuries (id, org_id, chain_id, asset_id) "
        f"VALUES ('{_TREASURY}', '{_ORG}', 11155111, '{_ASSET}')",
        "INSERT INTO vendors (id, org_id, name, normalized_ref) "
        f"VALUES ('{_VENDOR}', '{_ORG}', 'Vendor', 'vendor'), "
        f"('{_OTHER_VENDOR}', '{_ORG}', 'Other vendor', 'other-vendor')",
        "INSERT INTO payees (id, treasury_id, org_id, vendor_id, label, address, status, "
        "oob_verified_by, oob_verified_at, oob_method, oob_note, active_from) VALUES "
        f"('{_PAYEE}', '{_TREASURY}', '{_ORG}', '{_VENDOR}', 'Main', "
        f"decode(repeat('22', 20), 'hex'), 'Active', '{_USER}', now(), 'PHONE', 'verified', now()), "
        f"('{_OTHER_PAYEE}', '{_TREASURY}', '{_ORG}', '{_VENDOR}', 'Other', "
        f"decode(repeat('23', 20), 'hex'), 'Active', '{_USER}', now(), 'PHONE', 'verified', now()), "
        f"('{_OTHER_VENDOR_PAYEE}', '{_TREASURY}', '{_ORG}', '{_OTHER_VENDOR}', 'Other vendor', "
        f"decode(repeat('24', 20), 'hex'), 'Active', '{_USER}', now(), 'PHONE', 'verified', now())",
    ]
    try:
        async with engine.begin() as connection:
            for statement in statements:
                await connection.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the PostgreSQL request edit tests")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _run(database_url: str, scenario: Callable[[async_sessionmaker[AsyncSession]], Any]) -> Any:
    async def main() -> Any:
        engine = create_async_engine(database_url)
        try:
            return await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(main())


def _http(sessions: async_sessionmaker[AsyncSession]) -> Any:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(request_sessions=sessions)))


async def _create(sessions: async_sessionmaker[AsyncSession], invoice_no: str) -> dict[str, Any]:
    payload = RequestCreate(
        treasury_id=_TREASURY,
        vendor_id=_VENDOR,
        payee_id=_PAYEE,
        invoice_no=invoice_no,
        issue_date=date(2026, 10, 1),
        due_date=date(2026, 10, 31),
        amount="100",
        asset_id=_ASSET,
    )
    result = await create_request(
        _ORG, payload, _http(sessions), Response(), f"key-{invoice_no}", _MEMBER
    )
    return result["request"]  # type: ignore[no-any-return]


async def _patch(
    sessions: async_sessionmaker[AsyncSession], request: dict[str, Any], **fields: object
) -> dict[str, Any]:
    return await edit_request(
        _ORG,
        uuid.UUID(request["id"]),
        RequestPatch.model_validate(fields),
        _http(sessions),
        Response(),
        f'"{request["version"]}"',
        _MEMBER,
    )


async def _approve(sessions: async_sessionmaker[AsyncSession], request: dict[str, Any]) -> None:
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE payment_requests SET status = 'Approved' WHERE id = :id"),
            {"id": request["id"]},
        )
        await session.execute(
            text(
                "INSERT INTO approvals "
                "(id, request_id, revision, approver_address, typed_data, signature, expires_at) "
                "VALUES (:aid, :id, 1, decode(repeat('33', 20), 'hex'), '{}'::jsonb, "
                "decode('01', 'hex'), '2027-01-01T00:00:00Z')"
            ),
            {"aid": str(uuid.uuid4()), "id": request["id"]},
        )


async def _state(sessions: async_sessionmaker[AsyncSession], request: dict[str, Any]) -> Any:
    async with sessions() as session:
        return (
            await session.execute(
                text(
                    "SELECT r.status AS status, r.current_revision, r.due_at, r.amount, r.version, "
                    "(SELECT status FROM approvals WHERE request_id = r.id) AS approval "
                    "FROM payment_requests r WHERE r.id = :id"
                ),
                {"id": request["id"]},
            )
        ).one()


def test_due_date_only_patch_on_draft_is_saved_with_a_revision(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "DUE-DRAFT")
        result = await _patch(sessions, request, dueDate="2026-11-15")
        assert result["revision"] == 2
        assert result["request"]["dueDate"] == "2026-11-15"
        assert result["request"]["updatedAt"] is not None
        state = await _state(sessions, request)
        assert state.due_at == date(2026, 11, 15)
        assert state.current_revision == 2

    _run(database_url, scenario)


def test_due_date_only_patch_on_approved_invalidates_the_approval(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "DUE-APPROVED")
        await _approve(sessions, request)
        request["version"] = (await _state(sessions, request)).version
        result = await _patch(sessions, request, dueDate="2026-11-15")
        assert result["approvalInvalidated"] is True
        state = await _state(sessions, request)
        assert (state.status, state.due_at, state.approval) == (
            "Draft",
            date(2026, 11, 15),
            "Invalidated",
        )

    _run(database_url, scenario)


def test_amount_patch_on_approved_invalidates_the_approval(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "AMOUNT-APPROVED")
        await _approve(sessions, request)
        request["version"] = (await _state(sessions, request)).version
        result = await _patch(sessions, request, amount="250")
        state = await _state(sessions, request)
        assert result["approvalInvalidated"] is True
        assert (state.status, state.amount, state.current_revision, state.approval) == (
            "Draft",
            250_000_000,
            2,
            "Invalidated",
        )

    _run(database_url, scenario)


def test_resending_an_unchanged_amount_keeps_the_approval(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "AMOUNT-SAME")
        await _approve(sessions, request)
        request["version"] = (await _state(sessions, request)).version
        result = await _patch(sessions, request, amount="100.00", dueDate="2026-10-31")
        assert result["approvalInvalidated"] is False
        state = await _state(sessions, request)
        assert (state.status, state.current_revision, state.approval) == ("Approved", 1, "Valid")

    _run(database_url, scenario)


def test_free_field_patch_returns_the_updated_row(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "NOTE-ONLY")
        result = await _patch(sessions, request, note="paid by wire")
        assert result["request"]["note"] == "paid by wire"
        assert result["request"]["updatedAt"] is not None

    _run(database_url, scenario)


def test_note_patch_does_not_invalidate_an_approved_request(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "APPROVED-NOTE")
        await _approve(sessions, request)
        request["version"] = (await _state(sessions, request)).version
        result = await _patch(sessions, request, note="Updated remittance note")
        state = await _state(sessions, request)
        assert result["approvalInvalidated"] is False
        assert result["request"]["note"] == "Updated remittance note"
        assert (state.status, state.current_revision, state.approval) == (
            "Approved",
            1,
            "Valid",
        )

    _run(database_url, scenario)


def test_stale_if_match_on_patch_returns_412(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "STALE-ETAG")
        request["version"] = int(request["version"]) + 1
        with pytest.raises(AuthFailure) as error:
            await _patch(sessions, request, amount="125")
        assert (error.value.status, error.value.code) == (412, "PRECONDITION_FAILED")

    _run(database_url, scenario)


def test_create_rejects_asset_other_than_treasury_payment_stablecoin(
    database_url: str,
) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        payload = RequestCreate(
            treasury_id=_TREASURY,
            vendor_id=_VENDOR,
            payee_id=_PAYEE,
            invoice_no="WRONG-ASSET",
            issue_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31),
            amount="100",
            asset_id=_OTHER_ASSET,
        )
        with pytest.raises(AuthFailure) as error:
            await create_request(
                _ORG, payload, _http(sessions), Response(), "key-wrong-asset", _MEMBER
            )
        assert (error.value.status, error.value.code) == (422, "ASSET_NOT_PAYMENT_STABLECOIN")

    _run(database_url, scenario)


def test_create_rejects_payee_registered_to_another_vendor(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        payload = RequestCreate(
            treasury_id=_TREASURY,
            vendor_id=_OTHER_VENDOR,
            payee_id=_PAYEE,
            invoice_no="CROSS-VENDOR-PAYEE",
            issue_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31),
            amount="100",
            asset_id=_ASSET,
        )
        with pytest.raises(AuthFailure) as error:
            await create_request(
                _ORG, payload, _http(sessions), Response(), "key-cross-vendor", _MEMBER
            )
        assert (error.value.status, error.value.code) == (422, "PAYEE_NOT_OF_VENDOR")

    _run(database_url, scenario)


def test_deactivated_payee_does_not_block_correcting_other_bound_fields(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        request = await _create(sessions, "DEACTIVATED")
        async with sessions() as session, session.begin():
            await session.execute(
                text(
                    "UPDATE payees SET status = 'Deactivated', deactivated_at = now() WHERE id = :id"
                ),
                {"id": str(_PAYEE)},
            )
        try:
            result = await _patch(sessions, request, invoiceNo="DEACTIVATED-2")
            assert result["request"]["invoiceNo"] == "DEACTIVATED-2"
        finally:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("UPDATE payees SET status = 'Active' WHERE id = :id"),
                    {"id": str(_PAYEE)},
                )

    _run(database_url, scenario)


def test_unknown_treasury_is_a_specific_422(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        payload = RequestCreate(
            treasury_id=uuid.uuid4(),
            vendor_id=_VENDOR,
            payee_id=_PAYEE,
            invoice_no="NO-TREASURY",
            issue_date=date(2026, 10, 1),
            due_date=date(2026, 10, 31),
            amount="1",
            asset_id=_ASSET,
        )
        with pytest.raises(AuthFailure) as error:
            await create_request(_ORG, payload, _http(sessions), Response(), "k-no-t", _MEMBER)
        assert (error.value.status, error.value.code) == (422, "TREASURY_UNKNOWN")

    _run(database_url, scenario)


def test_edit_into_an_active_duplicate_is_a_409(database_url: str) -> None:
    async def scenario(sessions: async_sessionmaker[AsyncSession]) -> None:
        await _create(sessions, "DUP-A")
        other = await _create(sessions, "DUP-B")
        with pytest.raises(AuthFailure) as error:
            await _patch(sessions, other, invoiceNo="DUP-A")
        assert (error.value.status, error.value.code) == (409, "DUPLICATE_FINGERPRINT")

    _run(database_url, scenario)
