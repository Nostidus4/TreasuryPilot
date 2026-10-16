"""Config-driven data regions and region-bound object storage (CMP-L04, F-114).

This module is deliberately free of application imports so ``config`` can validate
``TP_DATA_REGIONS`` at startup. Nothing here contacts a cloud provider: each region is
just a set of endpoints (S3-compatible object storage and, optionally, a Postgres URL)
supplied by the operator.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Protocol
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

REGION_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class RegionError(Exception):
    """Base class; ``code`` is the stable problem code returned by the API."""

    code = "REGION_ERROR"
    status = 409


class UnknownRegionError(RegionError):
    code = "REGION_UNKNOWN"
    status = 422


class RegionUnavailableError(RegionError):
    code = "REGION_UNAVAILABLE"
    status = 503


class CrossRegionWriteError(RegionError):
    code = "CROSS_REGION_WRITE"
    status = 409


class RegionPinnedError(RegionError):
    code = "REGION_PINNED"
    status = 409


class RegionHasDataElsewhereError(RegionError):
    code = "REGION_HAS_DATA_ELSEWHERE"
    status = 409


class RegionEndpoint(BaseModel):
    """Endpoints for one region. Credentials are secrets and never logged."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    s3_endpoint_url: str
    s3_bucket: str
    s3_access_key: SecretStr
    s3_secret_key: SecretStr
    s3_public_endpoint_url: str | None = None
    database_url: SecretStr | None = None


class RegionStorage(Protocol):
    def put(self, object_key: str, body: bytes, content_type: str) -> None: ...

    def sign_read(self, object_key: str) -> str: ...

    def delete(self, object_key: str) -> None: ...


def _check_url(name: str, value: str | None, region: str) -> None:
    if value is None:
        return
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"TP_DATA_REGIONS[{region}].{name} must be an http(s) URL")


def parse_regions(raw: str) -> dict[str, RegionEndpoint]:
    """Parse and validate ``TP_DATA_REGIONS`` (JSON object of region id -> endpoints)."""

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("TP_DATA_REGIONS must be a JSON object") from exc
    if not isinstance(parsed, dict):
        raise ValueError("TP_DATA_REGIONS must be a JSON object")
    regions: dict[str, RegionEndpoint] = {}
    for name, config in parsed.items():
        if not isinstance(name, str) or not REGION_PATTERN.fullmatch(name):
            raise ValueError("Region ids must match ^[a-z][a-z0-9-]{1,31}$")
        try:
            endpoint = RegionEndpoint.model_validate(config)
        except ValidationError as exc:
            fields = ", ".join(str(error["loc"][0]) for error in exc.errors() if error["loc"])
            raise ValueError(f"TP_DATA_REGIONS[{name}] is invalid ({fields})") from None
        _check_url("s3_endpoint_url", endpoint.s3_endpoint_url, name)
        _check_url("s3_public_endpoint_url", endpoint.s3_public_endpoint_url, name)
        if not endpoint.s3_bucket.strip():
            raise ValueError(f"TP_DATA_REGIONS[{name}].s3_bucket must not be empty")
        regions[name] = endpoint
    # Two regions sharing one bucket (or one database) would make pinning meaningless.
    buckets = [(r.s3_endpoint_url.rstrip("/"), r.s3_bucket) for r in regions.values()]
    if len(set(buckets)) != len(buckets):
        raise ValueError("Each data region needs its own object storage endpoint and bucket")
    databases = [
        r.database_url.get_secret_value() for r in regions.values() if r.database_url is not None
    ]
    if len(set(databases)) != len(databases):
        raise ValueError("Each data region needs its own database_url")
    return regions


class RegionBoundStorage:
    """Object storage for exactly one organization in exactly one region.

    Every key must live under ``organizations/{org_id}/``; anything else is a
    cross-region (or cross-tenant) write and is refused before reaching the backend.
    """

    def __init__(self, inner: RegionStorage, org_id: uuid.UUID, region: str) -> None:
        self._inner, self.org_id, self.region = inner, org_id, region
        self._prefix = f"organizations/{org_id}/"

    def _check(self, object_key: str) -> None:
        if not object_key.startswith(self._prefix):
            raise CrossRegionWriteError(
                f"Object key is outside organization {self.org_id} in region {self.region}"
            )

    def put(self, object_key: str, body: bytes, content_type: str) -> None:
        self._check(object_key)
        self._inner.put(object_key, body, content_type)

    def sign_read(self, object_key: str) -> str:
        self._check(object_key)
        return self._inner.sign_read(object_key)

    def delete(self, object_key: str) -> None:
        self._check(object_key)
        self._inner.delete(object_key)


class RegionRegistry:
    """Resolves a region id to its storage and database; one instance per process."""

    def __init__(
        self,
        regions: Mapping[str, RegionEndpoint],
        local_region: str | None,
        storage_factory: Callable[[RegionEndpoint], RegionStorage | None],
    ) -> None:
        if local_region is not None and local_region not in regions:
            raise ValueError("TP_DATA_REGION must be one of the configured TP_DATA_REGIONS")
        self._regions = dict(regions)
        self.local_region = local_region
        self._storage_factory = storage_factory
        self._storage: dict[str, RegionStorage] = {}
        self._databases: dict[str, tuple[AsyncEngine, async_sessionmaker[AsyncSession]]] = {}

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._regions))

    def require(self, region: str) -> RegionEndpoint:
        try:
            return self._regions[region]
        except KeyError:
            raise UnknownRegionError(f"Region {region!r} is not configured") from None

    def assert_local(self, region: str) -> None:
        """Refuse work for a region this deployment (database) does not serve."""
        self.require(region)
        if self.local_region is not None and self.local_region != region:
            raise CrossRegionWriteError(
                f"This deployment serves region {self.local_region!r}, not {region!r}"
            )

    def storage(self, region: str) -> RegionStorage:
        if region not in self._storage:
            built = self._storage_factory(self.require(region))
            if built is None:
                raise RegionUnavailableError(f"Object storage for region {region!r} is unavailable")
            self._storage[region] = built
        return self._storage[region]

    def database(self, region: str) -> async_sessionmaker[AsyncSession]:
        """Session factory for the region's own Postgres (``database_url``), built lazily."""
        if region not in self._databases:
            url = self.require(region).database_url
            if url is None:
                raise RegionUnavailableError(f"Database for region {region!r} is not configured")
            engine = create_async_engine(url.get_secret_value(), pool_pre_ping=True)
            self._databases[region] = (engine, async_sessionmaker(engine, expire_on_commit=False))
        return self._databases[region][1]

    async def dispose(self) -> None:
        for engine, _ in self._databases.values():
            await engine.dispose()
        self._databases.clear()

    def bound_storage(self, region: str, org_id: uuid.UUID) -> RegionBoundStorage:
        self.assert_local(region)
        return RegionBoundStorage(self.storage(region), org_id, region)
