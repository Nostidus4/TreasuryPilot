from __future__ import annotations

import asyncio
import io
import json
import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx2 as httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from treasurypilot_api.admin.api import create_admin_router, create_data_region_router
from treasurypilot_api.audit.models import AuditLog
from treasurypilot_api.compliance.regions import (
    CrossRegionWriteError,
    RegionBoundStorage,
    RegionEndpoint,
    RegionHasDataElsewhereError,
    RegionPinnedError,
    RegionRegistry,
    RegionUnavailableError,
    UnknownRegionError,
    parse_regions,
)
from treasurypilot_api.compliance.residency import ResidencyService
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.rbac import MemberAccess, require_member
from treasurypilot_api.invoices import documents
from treasurypilot_api.invoices.models import RequestDocument

API_ROOT = Path(__file__).parents[1]
ADMIN_TOKEN = "x" * 48


def _regions(**extra: Any) -> str:
    def region(bucket: str, port: int) -> dict[str, Any]:
        return {
            "s3_endpoint_url": f"http://127.0.0.1:{port}",
            "s3_bucket": bucket,
            "s3_access_key": "test-access",
            "s3_secret_key": "test-secret",
            **extra,
        }

    return json.dumps({"eu": region("tp-eu", 9001), "us": region("tp-us", 9002)})


class FakeStorage:
    def __init__(self, name: str) -> None:
        self.name, self.objects = name, {}

    def put(self, object_key: str, body: bytes, content_type: str) -> None:
        self.objects[object_key] = body

    def sign_read(self, object_key: str) -> str:
        return f"https://{self.name}.test/{object_key}"

    def delete(self, object_key: str) -> None:
        self.objects.pop(object_key, None)


def _registry(local: str | None = "eu") -> tuple[RegionRegistry, dict[str, FakeStorage]]:
    stores: dict[str, FakeStorage] = {}

    def factory(endpoint: RegionEndpoint) -> FakeStorage:
        return stores.setdefault(endpoint.s3_bucket, FakeStorage(endpoint.s3_bucket))

    return RegionRegistry(parse_regions(_regions()), local, factory), stores


def test_parse_regions_validates_shape_and_isolation() -> None:
    assert set(parse_regions(_regions())) == {"eu", "us"}
    assert parse_regions("{}") == {}
    for bad in (
        "[]",
        "not json",
        json.dumps({"EU": {}}),
        json.dumps({"eu": {"s3_bucket": "b"}}),
        json.dumps({"eu": {**json.loads(_regions())["eu"], "extra": 1}}),
        json.dumps({"eu": {**json.loads(_regions())["eu"], "s3_endpoint_url": "ftp://x"}}),
    ):
        with pytest.raises(ValueError):
            parse_regions(bad)
    shared = json.loads(_regions())
    shared["us"]["s3_endpoint_url"], shared["us"]["s3_bucket"] = (
        shared["eu"]["s3_endpoint_url"],
        shared["eu"]["s3_bucket"],
    )
    with pytest.raises(ValueError, match="own object storage"):
        parse_regions(json.dumps(shared))
    same_db = json.loads(_regions(database_url="postgresql+asyncpg://u:p@h/d"))
    with pytest.raises(ValueError, match="own database_url"):
        parse_regions(json.dumps(same_db))


def test_settings_validate_regions_and_local_region() -> None:
    settings = Settings(_env_file=None, data_regions=_regions(), data_region="eu")  # type: ignore[call-arg]
    assert settings.data_region == "eu"
    with pytest.raises(ValueError, match="TP_DATA_REGION"):
        Settings(_env_file=None, data_regions=_regions(), data_region="apac")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        Settings(_env_file=None, data_regions="[]")  # type: ignore[call-arg]
    assert Settings(_env_file=None, data_region=" ").data_region is None  # type: ignore[call-arg]


def test_bound_storage_refuses_foreign_keys_and_other_regions() -> None:
    registry, stores = _registry("eu")
    org, other = uuid.uuid4(), uuid.uuid4()
    bound = registry.bound_storage("eu", org)
    bound.put(f"organizations/{org}/a", b"x", "text/plain")
    assert stores["tp-eu"].objects == {f"organizations/{org}/a": b"x"}
    for call in (
        lambda: bound.put(f"organizations/{other}/a", b"x", "text/plain"),
        lambda: bound.sign_read(f"organizations/{other}/a"),
        lambda: bound.delete("elsewhere/a"),
    ):
        with pytest.raises(CrossRegionWriteError):
            call()
    # A deployment serving "eu" must not write for a "us" org, and never touches its store.
    with pytest.raises(CrossRegionWriteError):
        registry.bound_storage("us", org)
    assert "tp-us" not in stores
    with pytest.raises(UnknownRegionError):
        registry.bound_storage("apac", org)
    assert isinstance(bound, RegionBoundStorage)


def test_unavailable_region_storage_fails_closed() -> None:
    registry = RegionRegistry(parse_regions(_regions()), None, lambda endpoint: None)
    with pytest.raises(RegionUnavailableError):
        registry.storage("eu")
    with pytest.raises(RegionUnavailableError):
        registry.database("eu")


def test_migration_sql_offline() -> None:
    output = io.StringIO()
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://offline/offline")
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    command.downgrade(config, "head:20261016_0088", sql=True)
    sql = output.getvalue()
    assert "CREATE TABLE org_data_regions" in sql
    assert "ADD COLUMN storage_region" in sql
    assert "a data region pin cannot be changed" in sql
    assert "DROP TABLE org_data_regions" in sql


# --- PostgreSQL (and optionally MinIO) integration ---------------------------------------

needs_db = pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL data region test",
)


def _alembic(database_url: str) -> Config:
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


async def _seed_org(
    sessions: async_sessionmaker[AsyncSession], with_treasury: bool = False
) -> uuid.UUID:
    org_id = uuid.uuid4()
    async with sessions() as session, session.begin():
        await session.execute(
            text("INSERT INTO organizations (id, name) VALUES (:id, 'Region test')"), {"id": org_id}
        )
        if with_treasury:
            asset_id, treasury_id = uuid.uuid4(), uuid.uuid4()
            await session.execute(
                text(
                    "INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url,"
                    " rpc_urls) VALUES (11155111, 'Sepolia', true, 3, 'https://e', '[\"https://rpc\"]')"
                    " ON CONFLICT DO NOTHING"
                )
            )
            await session.execute(
                text(
                    "INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label)"
                    " VALUES (:a, 11155111, decode(:addr, 'hex'), 'USDC', 6, 'Circle')"
                ),
                {"a": asset_id, "addr": os.urandom(20).hex()},
            )
            await session.execute(
                text(
                    "INSERT INTO treasuries (id, org_id, chain_id, asset_id)"
                    " VALUES (:t, :o, 11155111, :a)"
                ),
                {"t": treasury_id, "o": org_id, "a": asset_id},
            )
    return org_id


async def _treasury(sessions: async_sessionmaker[AsyncSession], org_id: uuid.UUID) -> uuid.UUID:
    async with sessions() as session:
        return cast(
            uuid.UUID,
            await session.scalar(
                text("SELECT id FROM treasuries WHERE org_id = :o"), {"o": org_id}
            ),
        )


class Queue:
    def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str:
        return job_id


def _request(
    sessions: async_sessionmaker[AsyncSession], residency: ResidencyService, default: Any
) -> Any:
    state = SimpleNamespace(
        request_sessions=sessions,
        residency=residency,
        document_storage=default,
        extraction_queue=Queue(),
    )
    return SimpleNamespace(app=SimpleNamespace(state=state))


async def _upload(request: Any, org_id: uuid.UUID, treasury_id: uuid.UUID) -> None:
    await documents.create_invoice_document_draft(
        request=request,
        organization_id=org_id,
        treasury_id=treasury_id,
        document=(b"%PDF-1.4 " + os.urandom(8), "application/pdf", 1),
        idempotency_key=uuid.uuid4().hex,
        uploaded_by=None,
    )


async def _scenario(database_url: str) -> None:
    engine = create_async_engine(database_url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    registry, stores = _registry("eu")
    default = FakeStorage("default")
    residency = ResidencyService(registry, default)
    try:
        legacy_org = await _seed_org(sessions, with_treasury=True)
        legacy_treasury = await _treasury(sessions, legacy_org)
        request = _request(sessions, residency, default)

        # Unpinned org: default store, documents tagged NULL.
        await _upload(request, legacy_org, legacy_treasury)
        assert len(default.objects) == 1 and not stores

        # Pinning is refused while data sits outside the region.
        async with sessions() as session, session.begin():
            with pytest.raises(RegionHasDataElsewhereError):
                await residency.pin(session, legacy_org, "eu", "ops@example.test")

        org = await _seed_org(sessions, with_treasury=True)
        treasury = await _treasury(sessions, org)
        async with sessions() as session, session.begin():
            assert await residency.pin(session, org, "eu", "ops@example.test") is True
        async with sessions() as session, session.begin():
            assert await residency.pin(session, org, "eu", "ops@example.test") is False
            with pytest.raises(RegionPinnedError):
                await residency.pin(session, org, "us", "ops@example.test")
        async with sessions() as session:
            audits = (
                await session.scalars(
                    select(AuditLog.action).where(
                        AuditLog.org_id == org, AuditLog.action.like("compliance.data_region.%")
                    )
                )
            ).all()
        assert list(audits) == ["compliance.data_region.pinned"]  # idempotent retry wrote none

        # The database itself refuses to move or drop a pin.
        for statement in (
            "UPDATE org_data_regions SET region = 'us' WHERE org_id = :o",
            "DELETE FROM org_data_regions WHERE org_id = :o",
        ):
            with pytest.raises(DBAPIError, match="cannot"):
                async with sessions() as session, session.begin():
                    await session.execute(text(statement), {"o": org})

        # A pinned org's upload lands only in its region's store, never the default store.
        before_default = dict(default.objects)
        await _upload(request, org, treasury)
        assert default.objects == before_default
        assert len(stores["tp-eu"].objects) == 1 and "tp-us" not in stores
        key = next(iter(stores["tp-eu"].objects))
        assert key.startswith(f"organizations/{org}/")
        async with sessions() as session:
            stored = await session.scalar(
                select(RequestDocument.storage_region).where(RequestDocument.storage_key == key)
            )
        assert stored == "eu"

        # A deployment serving another region refuses writes for this org.
        other_registry, other_stores = _registry("us")
        other = ResidencyService(other_registry, default)
        with pytest.raises(AuthFailure) as refused:
            await _upload(_request(sessions, other, default), org, treasury)
        assert refused.value.code == "CROSS_REGION_WRITE"
        assert not other_stores and len(stores["tp-eu"].objects) == 1

        # Admin API: pin, read back, conflict, unknown region; tenant read-only view.
        target = await _seed_org(sessions)
        settings = Settings(
            _env_file=None,  # type: ignore[call-arg]
            environment="local",
            admin_staff_token=ADMIN_TOKEN,  # type: ignore[arg-type]
            admin_staff_id="ops@example.test",
            admin_ip_allowlist="127.0.0.1/32",
            data_regions=_regions(),
            data_region="eu",
        )
        app = FastAPI()
        app.include_router(create_admin_router(settings, sessions, residency))
        app.include_router(create_data_region_router(sessions, residency))
        member = MemberAccess(
            access=SimpleNamespace(user=SimpleNamespace(id=uuid.uuid4())),  # type: ignore[arg-type]
            organization_id=target,
            roles=frozenset({"Auditor"}),
        )

        async def auditor() -> MemberAccess:
            return member

        app.dependency_overrides[require_member] = auditor
        auth = {"Authorization": f"Bearer {ADMIN_TOKEN}"}
        url = f"/admin/tenants/{target}/data-region"
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=("127.0.0.1", 50000)),
            base_url="http://test",
        ) as client:
            assert (await client.get(url)).status_code == 401
            initial = await client.get(url, headers=auth)
            assert initial.json()["region"] is None
            assert initial.json()["availableRegions"] == ["eu", "us"]
            bad = await client.put(url, headers=auth, json={"region": "apac"})
            assert bad.status_code == 422 and bad.json()["detail"]["code"] == "REGION_UNKNOWN"
            foreign = await client.put(url, headers=auth, json={"region": "us"})
            assert foreign.status_code == 409
            assert foreign.json()["detail"]["code"] == "CROSS_REGION_WRITE"
            ok = await client.put(url, headers=auth, json={"region": "eu"})
            assert ok.status_code == 200 and ok.json()["region"] == "eu"
            assert ok.json()["pinnedBy"] == "ops@example.test"
            repeat = await client.put(url, headers=auth, json={"region": "eu"})
            assert repeat.status_code == 200
            moved = await client.put(url, headers=auth, json={"region": "us"})
            assert moved.status_code == 409
            missing = await client.put(
                f"/admin/tenants/{uuid.uuid4()}/data-region", headers=auth, json={"region": "eu"}
            )
            assert missing.status_code == 404
            view = await client.get(f"/v1/orgs/{target}/data-region")
            assert view.status_code == 200 and view.json()["region"] == "eu"
    finally:
        await engine.dispose()


async def _reset_schema(database_url: str) -> None:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        await connection.execute(text("DROP SCHEMA IF EXISTS signer CASCADE"))
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    await engine.dispose()


@needs_db
def test_region_pinning_on_postgres() -> None:
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    config = _alembic(database_url)
    command.upgrade(config, "head")
    try:
        asyncio.run(_scenario(database_url))
    finally:
        # The scenario leaves upload drafts that the invoice migration refuses to downgrade
        # past; reset the throwaway test schema instead.
        asyncio.run(_reset_schema(database_url))


@pytest.mark.skipif(
    "TP_TEST_S3_ENDPOINT" not in os.environ,
    reason="TP_TEST_S3_ENDPOINT (a local MinIO) is required for the object storage infra test",
)
def test_pinned_data_lands_only_in_region_bucket_on_minio() -> None:
    from minio import Minio

    endpoint = os.environ["TP_TEST_S3_ENDPOINT"]
    access, secret = os.environ["TP_TEST_S3_ACCESS_KEY"], os.environ["TP_TEST_S3_SECRET_KEY"]
    host = endpoint.removeprefix("http://")
    client = Minio(host, access_key=access, secret_key=secret, secure=False)
    suffix = uuid.uuid4().hex[:8]
    buckets = {"eu": f"tp-eu-{suffix}", "us": f"tp-us-{suffix}"}
    for bucket in buckets.values():
        client.make_bucket(bucket)
    config = {
        region: {
            "s3_endpoint_url": endpoint,
            "s3_bucket": bucket,
            "s3_access_key": access,
            "s3_secret_key": secret,
        }
        for region, bucket in buckets.items()
    }
    # Same MinIO server, distinct buckets: the isolation key is (endpoint, bucket).
    settings = Settings(_env_file=None, data_regions=json.dumps(config), data_region="eu")  # type: ignore[call-arg]
    registry = RegionRegistry(
        parse_regions(settings.data_regions),
        "eu",
        lambda ep: documents.build_region_storage(settings, ep),
    )
    org = uuid.uuid4()
    try:
        storage = registry.bound_storage("eu", org)
        key = f"organizations/{org}/requests/r/d"
        storage.put(key, b"private", "application/pdf")
        assert [o.object_name for o in client.list_objects(buckets["eu"], recursive=True)] == [key]
        assert list(client.list_objects(buckets["us"], recursive=True)) == []
        with pytest.raises(CrossRegionWriteError):
            registry.bound_storage("us", org)
        with pytest.raises(CrossRegionWriteError):
            storage.put("organizations/other/x", b"x", "text/plain")
        assert list(client.list_objects(buckets["us"], recursive=True)) == []
        storage.delete(key)
    finally:
        for bucket in buckets.values():
            for obj in client.list_objects(bucket, recursive=True):
                client.remove_object(bucket, cast(str, obj.object_name))
            client.remove_bucket(bucket)
