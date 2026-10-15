from __future__ import annotations

import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, cast

from fastapi import APIRouter, Depends, Request, Response
from pydantic import Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.events import AuditEvent, AuditWriter, log_audit_event
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.mandate.models import Payee, Vendor


class VendorRefExists(Exception):
    """Another vendor of the organization already has this normalized reference."""


class VendorHasPayees(Exception):
    """A vendor with payee history cannot be deleted."""


class FieldCipher(Protocol):
    """Application-level encryption for confidential vendor identifiers."""

    def encrypt(self, plaintext: str) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> str: ...


def normalize_vendor_ref(value: str) -> str:
    """Return the stable, case/spacing-insensitive reference of a vendor name or code."""

    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


@dataclass(frozen=True, slots=True)
class VendorRecord:
    id: uuid.UUID
    org_id: uuid.UUID
    name: str
    normalized_ref: str
    has_tax_id: bool
    has_contact: bool
    notes: str | None
    created_at: datetime
    country: str | None = None


@dataclass(frozen=True, slots=True)
class VendorUpdate:
    name: str | None = None
    country: str | None = None
    notes: str | None = None
    tax_id: bytes | None = None
    contact: bytes | None = None
    clear_tax_id: bool = False
    clear_contact: bool = False


class VendorRepository(Protocol):
    async def list_vendors(self, *, organization_id: uuid.UUID) -> tuple[VendorRecord, ...]: ...

    async def get_vendor(
        self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> VendorRecord | None: ...

    async def create_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        country: str | None,
        normalized_ref: str,
        tax_id: bytes | None,
        contact: bytes | None,
        notes: str | None,
    ) -> VendorRecord:
        """Raise ``VendorRefExists`` when the reference is taken."""
        ...

    async def update_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        vendor_id: uuid.UUID,
        update: VendorUpdate,
        changed: tuple[str, ...],
    ) -> VendorRecord | None: ...

    async def delete_vendor(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> bool:
        """Return False when missing; raise ``VendorHasPayees`` when payees exist."""
        ...


def _record(row: Vendor) -> VendorRecord:
    return VendorRecord(
        id=row.id,
        org_id=row.org_id,
        name=row.name,
        country=row.country,
        normalized_ref=row.normalized_ref,
        has_tax_id=row.tax_id_encrypted is not None,
        has_contact=row.contact_encrypted is not None,
        notes=row.notes,
        created_at=row.created_at,
    )


class SqlAlchemyVendorRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        audit_writer: AuditWriter = log_audit_event,
    ) -> None:
        self._sessions = sessions
        self._audit = audit_writer

    async def list_vendors(self, *, organization_id: uuid.UUID) -> tuple[VendorRecord, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(Vendor).where(Vendor.org_id == organization_id).order_by(Vendor.name)
            )
            return tuple(_record(row) for row in rows)

    async def get_vendor(
        self, *, organization_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> VendorRecord | None:
        async with self._sessions() as session:
            row = await session.scalar(
                select(Vendor).where(Vendor.org_id == organization_id, Vendor.id == vendor_id)
            )
            return _record(row) if row is not None else None

    async def create_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        name: str,
        country: str | None,
        normalized_ref: str,
        tax_id: bytes | None,
        contact: bytes | None,
        notes: str | None,
    ) -> VendorRecord:
        try:
            async with self._sessions() as session, session.begin():
                existing = await session.scalar(
                    select(Vendor.id).where(
                        Vendor.org_id == organization_id,
                        Vendor.normalized_ref == normalized_ref,
                    )
                )
                if existing is not None:
                    raise VendorRefExists
                row = Vendor(
                    id=uuid7(),
                    org_id=organization_id,
                    name=name,
                    country=country,
                    normalized_ref=normalized_ref,
                    tax_id_encrypted=tax_id,
                    contact_encrypted=contact,
                    notes=notes,
                    created_by=user_id,
                )
                session.add(row)
                await session.flush()
                await self._audit(
                    session,
                    AuditEvent(
                        org_id=organization_id,
                        actor_id=user_id,
                        action="vendor.created",
                        entity_type="vendor",
                        entity_id=row.id,
                        data={"normalizedRef": normalized_ref},
                    ),
                )
                return _record(row)
        except IntegrityError as error:
            # A concurrent request won the unique(org_id, normalized_ref) race.
            raise VendorRefExists from error

    async def update_vendor(
        self,
        *,
        organization_id: uuid.UUID,
        user_id: uuid.UUID,
        vendor_id: uuid.UUID,
        update: VendorUpdate,
        changed: tuple[str, ...],
    ) -> VendorRecord | None:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Vendor)
                .where(Vendor.org_id == organization_id, Vendor.id == vendor_id)
                .with_for_update()
            )
            if row is None:
                return None
            # normalized_ref is set once: renaming never changes it (M05-D2).
            if update.name is not None:
                row.name = update.name
            if "country" in changed:
                row.country = update.country
            if update.notes is not None:
                row.notes = update.notes
            if update.tax_id is not None:
                row.tax_id_encrypted = update.tax_id
            elif update.clear_tax_id:
                row.tax_id_encrypted = None
            if update.contact is not None:
                row.contact_encrypted = update.contact
            elif update.clear_contact:
                row.contact_encrypted = None
            await session.flush()
            await self._audit(
                session,
                AuditEvent(
                    org_id=organization_id,
                    actor_id=user_id,
                    action="vendor.updated",
                    entity_type="vendor",
                    entity_id=row.id,
                    data={"fields": list(changed)},
                ),
            )
            return _record(row)

    async def delete_vendor(
        self, *, organization_id: uuid.UUID, user_id: uuid.UUID, vendor_id: uuid.UUID
    ) -> bool:
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(Vendor)
                .where(Vendor.org_id == organization_id, Vendor.id == vendor_id)
                .with_for_update()
            )
            if row is None:
                return False
            has_payee = await session.scalar(
                select(Payee.id).where(Payee.vendor_id == vendor_id).limit(1)
            )
            if has_payee is not None:
                raise VendorHasPayees
            await session.execute(delete(Vendor).where(Vendor.id == vendor_id))
            await self._audit(
                session,
                AuditEvent(
                    org_id=organization_id,
                    actor_id=user_id,
                    action="vendor.deleted",
                    entity_type="vendor",
                    entity_id=vendor_id,
                    data={"normalizedRef": row.normalized_ref},
                ),
            )
            return True


class VendorCreate(ApiModel):
    name: str = Field(min_length=1, max_length=200)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    # Optional stable supplier code; the reference is normalized from it, else from the name.
    supplier_code: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=100)
    contact: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name", "supplier_code")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class VendorPatch(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    country: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}$")
    tax_id: str | None = Field(default=None, max_length=100)
    contact: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("name")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("country")
    @classmethod
    def uppercase_country(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None


class VendorView(ApiModel):
    id: uuid.UUID
    name: str
    country: str | None
    normalized_ref: str
    has_tax_id: bool
    has_contact: bool
    notes: str | None
    created_at: datetime

    @classmethod
    def from_record(cls, row: VendorRecord) -> VendorView:
        return cls(
            id=row.id,
            name=row.name,
            country=row.country,
            normalized_ref=row.normalized_ref,
            has_tax_id=row.has_tax_id,
            has_contact=row.has_contact,
            notes=row.notes,
            created_at=row.created_at,
        )


class VendorResponse(ApiModel):
    vendor: VendorView


class VendorListResponse(ApiModel):
    items: list[VendorView]


def _repository(request: Request) -> VendorRepository:
    repository = getattr(request.app.state, "vendor_repository", None)
    if repository is None:
        raise AuthFailure(
            status=503,
            code="VENDOR_UNAVAILABLE",
            title="Vendor service unavailable",
            detail="Vendor storage is not configured.",
        )
    return cast(VendorRepository, repository)


def _encrypt(request: Request, value: str | None) -> bytes | None:
    if value is None:
        return None
    cipher = getattr(request.app.state, "field_cipher", None)
    if cipher is None:
        # Fail closed: confidential identifiers are never stored unencrypted.
        raise AuthFailure(
            status=503,
            code="ENCRYPTION_UNAVAILABLE",
            title="Encryption unavailable",
            detail="Confidential vendor fields cannot be stored: no field cipher is configured.",
        )
    return cast(FieldCipher, cipher).encrypt(value)


def vendor_not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="VENDOR_NOT_FOUND",
        title="Vendor not found",
        detail="The vendor does not exist in this organization.",
    )


router = APIRouter(prefix="/v1/orgs/{organization_id}/vendors", tags=["vendors"])
_require_editor = require_role(
    OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER
)
_require_admin = require_role(OrganizationRole.ORG_ADMIN, OrganizationRole.OWNER)


@router.get("", response_model=VendorListResponse, openapi_extra={"x-organization-scoped": True})
async def list_vendors(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> VendorListResponse:
    rows = await _repository(request).list_vendors(organization_id=member.organization_id)
    return VendorListResponse(items=[VendorView.from_record(row) for row in rows])


@router.post(
    "",
    status_code=201,
    response_model=VendorResponse,
    openapi_extra={"x-organization-scoped": True},
)
async def create_vendor(
    organization_id: uuid.UUID,
    payload: VendorCreate,
    request: Request,
    response: Response,
    member: MemberAccess = Depends(_require_editor),  # noqa: B008
) -> VendorResponse:
    normalized_ref = normalize_vendor_ref(payload.supplier_code or payload.name)
    if not normalized_ref:
        raise AuthFailure(
            status=422,
            code="VENDOR_REF_INVALID",
            title="Vendor reference invalid",
            detail="The vendor name or supplier code must contain visible characters.",
        )
    tax_id = _encrypt(request, payload.tax_id)
    contact = _encrypt(request, payload.contact)
    try:
        row = await _repository(request).create_vendor(
            organization_id=member.organization_id,
            user_id=member.user_id,
            name=payload.name,
            country=payload.country,
            normalized_ref=normalized_ref,
            tax_id=tax_id,
            contact=contact,
            notes=payload.notes,
        )
    except VendorRefExists:
        raise AuthFailure(
            status=409,
            code="VENDOR_REF_EXISTS",
            title="Vendor already exists",
            detail="A vendor with the same normalized reference already exists.",
        ) from None
    response.headers["Location"] = f"/v1/orgs/{organization_id}/vendors/{row.id}"
    return VendorResponse(vendor=VendorView.from_record(row))


@router.get(
    "/{vendor_id}", response_model=VendorResponse, openapi_extra={"x-organization-scoped": True}
)
async def get_vendor(
    organization_id: uuid.UUID,
    vendor_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> VendorResponse:
    row = await _repository(request).get_vendor(
        organization_id=member.organization_id, vendor_id=vendor_id
    )
    if row is None:
        raise vendor_not_found()
    return VendorResponse(vendor=VendorView.from_record(row))


@router.patch(
    "/{vendor_id}", response_model=VendorResponse, openapi_extra={"x-organization-scoped": True}
)
async def update_vendor(
    organization_id: uuid.UUID,
    vendor_id: uuid.UUID,
    payload: VendorPatch,
    request: Request,
    member: MemberAccess = Depends(_require_editor),  # noqa: B008
) -> VendorResponse:
    sent = payload.model_fields_set
    update = VendorUpdate(
        name=payload.name,
        country=payload.country,
        notes=payload.notes,
        tax_id=_encrypt(request, payload.tax_id),
        contact=_encrypt(request, payload.contact),
        clear_tax_id="tax_id" in sent and payload.tax_id is None,
        clear_contact="contact" in sent and payload.contact is None,
    )
    changed = tuple(sorted(sent & {"name", "country", "tax_id", "contact", "notes"}))
    row = await _repository(request).update_vendor(
        organization_id=member.organization_id,
        user_id=member.user_id,
        vendor_id=vendor_id,
        update=update,
        changed=changed,
    )
    if row is None:
        raise vendor_not_found()
    return VendorResponse(vendor=VendorView.from_record(row))


@router.delete(
    "/{vendor_id}",
    status_code=204,
    response_model=None,
    openapi_extra={"x-organization-scoped": True},
)
async def delete_vendor(
    organization_id: uuid.UUID,
    vendor_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_admin),  # noqa: B008
) -> Response:
    try:
        deleted = await _repository(request).delete_vendor(
            organization_id=member.organization_id,
            user_id=member.user_id,
            vendor_id=vendor_id,
        )
    except VendorHasPayees:
        raise AuthFailure(
            status=409,
            code="VENDOR_HAS_PAYEES",
            title="Vendor has payees",
            detail="A vendor with payees cannot be deleted.",
        ) from None
    if not deleted:
        raise vendor_not_found()
    return Response(status_code=204)
