"""Per-organization data region pinning (CMP-L04, F-114).

A pinned organization's documents are written only to its region's object store, and
only by a deployment whose database serves that region. A pin never falls back to the
default store: an unreachable region fails closed with ``REGION_UNAVAILABLE``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.compliance.models import OrgDataRegion
from treasurypilot_api.compliance.regions import (
    RegionHasDataElsewhereError,
    RegionPinnedError,
    RegionRegistry,
    RegionStorage,
)
from treasurypilot_api.identity.models import Organization
from treasurypilot_api.invoices.models import PaymentRequest, RequestDocument


class ResidencyService:
    def __init__(self, registry: RegionRegistry, default_storage: RegionStorage | None) -> None:
        self.registry = registry
        self.default_storage = default_storage

    async def region_of(self, session: AsyncSession, org_id: uuid.UUID) -> str | None:
        return await session.scalar(
            select(OrgDataRegion.region).where(OrgDataRegion.org_id == org_id)
        )

    async def storage_for_org(
        self, factory: async_sessionmaker[AsyncSession], org_id: uuid.UUID
    ) -> tuple[RegionStorage | None, str | None]:
        """Storage a write for ``org_id`` must use, with its region (None = unpinned)."""
        async with factory() as session:
            region = await self.region_of(session, org_id)
        if region is None:
            return self.default_storage, None
        return self.registry.bound_storage(region, org_id), region

    def storage_for_document(
        self, org_id: uuid.UUID, document_region: str | None
    ) -> RegionStorage | None:
        """Storage that holds an existing document, from the region recorded on its row."""
        if document_region is None:
            return self.default_storage
        return self.registry.bound_storage(document_region, org_id)

    async def pin(self, session: AsyncSession, org_id: uuid.UUID, region: str, actor: str) -> bool:
        """Pin ``org_id`` to ``region`` inside the caller's transaction.

        Returns False when already pinned to the same region (idempotent, no audit entry).
        Refuses an unknown region, a region this deployment does not serve, a different
        existing pin, and an organization that already holds data outside ``region``.
        """
        self.registry.require(region)
        org = await session.get(Organization, org_id, with_for_update=True)
        if org is None:
            raise LookupError("organization not found")
        existing = await self.region_of(session, org_id)
        if existing == region:
            return False
        if existing is not None:
            raise RegionPinnedError(
                f"Organization is pinned to {existing!r}; moving it needs a data migration"
            )
        self.registry.assert_local(region)
        self.registry.storage(region)  # fail closed if the region has no usable store
        elsewhere = await session.scalar(
            select(func.count())
            .select_from(RequestDocument)
            .join(PaymentRequest, PaymentRequest.id == RequestDocument.request_id)
            .where(
                PaymentRequest.org_id == org_id,
                RequestDocument.storage_region.is_distinct_from(region),
            )
        )
        if elsewhere:
            raise RegionHasDataElsewhereError(
                f"{elsewhere} stored document(s) are outside {region!r}; migrate them first"
            )
        session.add(OrgDataRegion(org_id=org_id, region=region, pinned_by=actor))
        await write_audit(
            session,
            org_id=org_id,
            actor=AuditActor(AuditActorType.SYSTEM, actor),
            action="compliance.data_region.pinned",
            entity=AuditEntity("organization", org_id),
            data={"region": region, "pinned_by": actor},
        )
        return True
