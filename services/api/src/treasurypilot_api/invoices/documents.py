"""Private invoice document storage and upload-to-extraction handoff (INV-004)."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from typing import Protocol, cast
from urllib.parse import urlparse

from celery import Celery
from fastapi import APIRouter, Depends, File, Form, Header, Request, UploadFile
from minio import Minio
from PIL import Image
from pydantic import Field
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from treasurypilot_api.config import Settings
from treasurypilot_api.identity.access import MemberContext, require_member, require_role
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.invoices.models import (
    PaymentRequest,
    RequestDocument,
    RequestFlag,
    RequestFlagSeverity,
    RequestFlagSource,
    RequestFlagStatus,
    RequestRevision,
    RequestSource,
    RequestStatus,
)
from treasurypilot_api.mandate.models import Payee, Vendor
from treasurypilot_api.treasury.models import Asset, Treasury

router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["invoice documents"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_PAGES = 20
PRESIGNED_URL_LIFETIME = timedelta(minutes=5)
EXTRACTION_TASK = "treasurypilot.invoices.extract_document"


class ObjectStorage(Protocol):
    def put(self, object_key: str, body: bytes, content_type: str) -> None: ...

    def sign_read(self, object_key: str) -> str: ...

    def delete(self, object_key: str) -> None: ...


class ExtractionQueue(Protocol):
    def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str: ...


class MinioObjectStorage:
    """S3-compatible storage adapter; buckets remain private by default."""

    def __init__(self, client: Minio, bucket: str) -> None:
        self.client = client
        self.bucket = bucket

    def put(self, object_key: str, body: bytes, content_type: str) -> None:
        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(body),
            length=len(body),
            content_type=content_type,
        )

    def sign_read(self, object_key: str) -> str:
        return self.client.presigned_get_object(
            self.bucket, object_key, expires=PRESIGNED_URL_LIFETIME
        )

    def delete(self, object_key: str) -> None:
        self.client.remove_object(self.bucket, object_key)


class CeleryExtractionQueue:
    def __init__(self, broker_url: str) -> None:
        self.client = Celery("treasurypilot-api", broker=broker_url)

    def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str:
        result = self.client.send_task(
            EXTRACTION_TASK,
            args=[str(request_id), str(document_id)],
            task_id=job_id,
            queue="ai",
        )
        return str(result.id)


def build_document_storage(settings: Settings) -> ObjectStorage | None:
    values = (
        settings.s3_endpoint_url,
        settings.s3_bucket,
        settings.s3_access_key,
        settings.s3_secret_key,
    )
    if not any(values):
        return None
    if any(value is None for value in values):
        raise ValueError("S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY and S3_SECRET_KEY are required")
    parsed = urlparse(cast(str, settings.s3_endpoint_url))
    if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
        raise ValueError("S3_ENDPOINT_URL must be an http(s) URL")
    endpoint = parsed.netloc
    client = Minio(
        endpoint,
        access_key=cast(object, settings.s3_access_key).get_secret_value(),  # type: ignore[attr-defined]
        secret_key=cast(object, settings.s3_secret_key).get_secret_value(),  # type: ignore[attr-defined]
        secure=parsed.scheme == "https",
    )
    return MinioObjectStorage(client, cast(str, settings.s3_bucket))


def build_extraction_queue(settings: Settings) -> ExtractionQueue | None:
    if settings.redis_url is None:
        return None
    return CeleryExtractionQueue(settings.redis_url.get_secret_value())


def _fail(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    factory = getattr(request.app.state, "request_sessions", None)
    if factory is None:
        raise _fail(
            503,
            "REQUESTS_UNAVAILABLE",
            "Requests unavailable",
            "Request storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], factory)


def _storage(request: Request) -> ObjectStorage:
    storage = getattr(request.app.state, "document_storage", None)
    if storage is None:
        raise _fail(
            503,
            "DOCUMENT_STORAGE_UNAVAILABLE",
            "Document storage unavailable",
            "Private invoice document storage is not configured.",
        )
    return cast(ObjectStorage, storage)


def _queue(request: Request) -> ExtractionQueue:
    queue = getattr(request.app.state, "extraction_queue", None)
    if queue is None:
        raise _fail(
            503,
            "EXTRACTION_QUEUE_UNAVAILABLE",
            "Extraction queue unavailable",
            "Invoice extraction cannot be scheduled right now.",
        )
    return cast(ExtractionQueue, queue)


async def _read_document(file: UploadFile) -> tuple[bytes, str, int]:
    data = bytearray()
    while chunk := await file.read(64 * 1024):
        data.extend(chunk)
        if len(data) > MAX_DOCUMENT_BYTES:
            raise _fail(
                413,
                "DOCUMENT_TOO_LARGE",
                "Document too large",
                "Invoice documents must be no larger than 10 MiB.",
            )
    body = bytes(data)
    filename = (file.filename or "").lower()
    try:
        if body.startswith(b"%PDF-") and filename.endswith(".pdf"):
            reader = PdfReader(BytesIO(body), strict=True)
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported")
            pages = len(reader.pages)
            mime = "application/pdf"
        elif body.startswith(b"\x89PNG\r\n\x1a\n") and filename.endswith(".png"):
            with Image.open(BytesIO(body)) as image:
                if image.format != "PNG":
                    raise ValueError("PNG signature does not match image format")
                image.verify()
            pages, mime = 1, "image/png"
        elif body.startswith(b"\xff\xd8\xff") and filename.endswith((".jpg", ".jpeg")):
            with Image.open(BytesIO(body)) as image:
                if image.format != "JPEG":
                    raise ValueError("JPEG signature does not match image format")
                image.verify()
            pages, mime = 1, "image/jpeg"
        else:
            raise ValueError("File content or extension is not a supported PDF, PNG or JPEG")
    except Exception as error:
        if isinstance(error, AuthFailure):
            raise
        raise _fail(
            415,
            "UNSUPPORTED_DOCUMENT_TYPE",
            "Unsupported document type",
            "Upload a valid PDF, PNG or JPEG invoice file.",
        ) from error
    if pages < 1:
        raise _fail(
            415,
            "UNSUPPORTED_DOCUMENT_TYPE",
            "Unsupported document type",
            "The invoice document must contain at least one page.",
        )
    if pages > MAX_DOCUMENT_PAGES:
        raise _fail(
            413,
            "DOCUMENT_TOO_MANY_PAGES",
            "Document has too many pages",
            "Invoice documents must contain no more than 20 pages.",
        )
    return body, mime, pages


class UploadResponse(ApiModel):
    request_id: uuid.UUID
    document_id: uuid.UUID
    extraction_job_id: str


class DocumentUrlResponse(ApiModel):
    url: str
    expires_at: datetime


class ExtractionConfirmation(ApiModel):
    vendor_id: uuid.UUID
    payee_id: uuid.UUID
    invoice_no: str = Field(min_length=1, max_length=200)
    issue_date: date
    due_date: date
    amount: str = Field(min_length=1, max_length=80)
    invoice_count_in_document: int = Field(default=1, ge=1)


@router.post("/upload", status_code=202, openapi_extra={"x-organization-scoped": True})
async def upload_invoice_document(
    organization_id: uuid.UUID,
    request: Request,
    treasury_id: uuid.UUID = Form(),  # noqa: B008
    file: UploadFile = File(),  # noqa: B008
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> UploadResponse:
    if organization_id != member.organization_id:
        raise _fail(
            404, "ORGANIZATION_NOT_FOUND", "Organization not found", "Organization not found."
        )
    if idempotency_key is None:
        raise _fail(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency key required",
            "Provide an Idempotency-Key for this upload.",
        )
    body, mime, pages = await _read_document(file)
    digest = hashlib.sha256(body).digest()
    storage = _storage(request)
    queue = _queue(request)
    factory = _sessions(request)

    async with factory() as session:
        treasury = await session.scalar(
            select(Treasury).where(
                Treasury.id == treasury_id, Treasury.org_id == member.organization_id
            )
        )
        if treasury is None:
            raise _fail(404, "TREASURY_NOT_FOUND", "Treasury not found", "Treasury not found.")
        asset = await session.scalar(
            select(Asset).where(Asset.id == treasury.asset_id, Asset.chain_id == treasury.chain_id)
        )
        if asset is None:
            raise _fail(
                422,
                "ASSET_NOT_PAYMENT_STABLECOIN",
                "Payment asset invalid",
                "The treasury payment asset is unavailable.",
            )

    payload_hash = hashlib.sha256(treasury_id.bytes + digest).digest()
    async with factory() as session:
        previous = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.org_id == member.organization_id,
                PaymentRequest.idempotency_key == idempotency_key,
            )
        )
        if previous is not None:
            if previous.idempotency_payload_hash != payload_hash:
                raise _fail(
                    409,
                    "IDEMPOTENCY_KEY_REUSED",
                    "Idempotency key reused",
                    "Use a new key when the upload changes.",
                )
            document = await session.scalar(
                select(RequestDocument).where(RequestDocument.request_id == previous.id)
            )
            if document is None:
                raise _fail(
                    503,
                    "DOCUMENT_UNAVAILABLE",
                    "Document unavailable",
                    "The previous upload is incomplete; retry with a new idempotency key.",
                )
            request_id, document_id = previous.id, document.id
        else:
            request_id, document_id = uuid7(), uuid7()
            object_key = (
                f"organizations/{member.organization_id}/requests/{request_id}/{document_id}"
            )
            try:
                await run_in_threadpool(storage.put, object_key, body, mime)
            except Exception as error:
                raise _fail(
                    503,
                    "DOCUMENT_STORAGE_UNAVAILABLE",
                    "Document storage unavailable",
                    "The invoice file could not be stored.",
                ) from error

            row = PaymentRequest(
                id=request_id,
                org_id=member.organization_id,
                treasury_id=treasury.id,
                chain_id=treasury.chain_id,
                vendor_id=None,
                payee_id=None,
                invoice_no=None,
                issue_date=None,
                due_at=None,
                amount=None,
                asset_id=asset.id,
                source=RequestSource.UPLOAD.value,
                status=RequestStatus.DRAFT.value,
                current_revision=1,
                created_by=member.user_id,
                last_edited_by=member.user_id,
                onchain_request_id=_onchain_request_id(member.organization_id, request_id),
                idempotency_key=idempotency_key,
                idempotency_payload_hash=payload_hash,
            )
            revision = RequestRevision(
                id=uuid7(),
                request_id=request_id,
                revision=1,
                edited_by=member.user_id,
                snapshot={
                    "treasuryId": str(treasury.id),
                    "vendorId": None,
                    "payeeId": None,
                    "invoiceNo": None,
                    "issueDate": None,
                    "dueDate": None,
                    "amount": None,
                    "assetId": str(asset.id),
                },
                reason="invoice document uploaded",
            )
            document = RequestDocument(
                id=document_id,
                request_id=request_id,
                storage_key=object_key,
                sha256=digest,
                mime=mime,
                size=len(body),
                pages=pages,
                uploaded_by=member.user_id,
            )
            try:
                async with factory() as write_session, write_session.begin():
                    write_session.add_all([row, revision, document])
            except Exception:
                await run_in_threadpool(storage.delete, object_key)
                raise

    job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"treasurypilot:invoice-extract:{request_id}").hex
    try:
        scheduled_id = await run_in_threadpool(queue.enqueue, request_id, document_id, job_id)
    except Exception as error:
        raise _fail(
            503,
            "EXTRACTION_QUEUE_UNAVAILABLE",
            "Extraction queue unavailable",
            "The document is stored but extraction could not be scheduled.",
        ) from error
    return UploadResponse(
        request_id=request_id, document_id=document_id, extraction_job_id=scheduled_id
    )


@router.post("/{request_id}/extraction/confirm", openapi_extra={"x-organization-scoped": True})
async def confirm_extraction(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: ExtractionConfirmation,
    request: Request,
    member: MemberContext = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    """Apply operator-reviewed extraction fields to the current upload draft."""
    if organization_id != member.organization_id:
        raise _fail(
            404, "ORGANIZATION_NOT_FOUND", "Organization not found", "Organization not found."
        )
    from treasurypilot_api.invoices.requests import _amount, _hashes, _validate_dates

    _validate_dates(payload.issue_date, payload.due_date)
    factory = _sessions(request)
    if payload.invoice_count_in_document > 1:
        async with factory() as session, session.begin():
            row = await session.scalar(
                select(PaymentRequest)
                .where(
                    PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id
                )
                .with_for_update()
            )
            if row is None:
                raise _fail(404, "REQUEST_NOT_FOUND", "Request not found", "Request not found.")
            session.add(
                RequestFlag(
                    id=uuid7(),
                    request_id=row.id,
                    revision=row.current_revision,
                    code="MULTI_INVOICE_DOCUMENT",
                    severity=RequestFlagSeverity.HIGH.value,
                    evidence={"invoiceCountInDocument": payload.invoice_count_in_document},
                    source=RequestFlagSource.AI.value,
                    status=RequestFlagStatus.OPEN.value,
                )
            )
        raise _fail(
            422,
            "MULTI_INVOICE_DOCUMENT",
            "Multiple invoices detected",
            "Upload one invoice per document; this extraction cannot be confirmed.",
        )
    async with factory() as session, session.begin():
        row = await session.scalar(
            select(PaymentRequest)
            .where(PaymentRequest.id == request_id, PaymentRequest.org_id == member.organization_id)
            .with_for_update()
        )
        if row is None:
            raise _fail(404, "REQUEST_NOT_FOUND", "Request not found", "Request not found.")
        if row.source != RequestSource.UPLOAD.value or row.status != RequestStatus.DRAFT.value:
            raise _fail(
                409,
                "REQUEST_NOT_EDITABLE",
                "Request not editable",
                "Only upload drafts can be confirmed.",
            )
        treasury = await session.scalar(
            select(Treasury).where(
                Treasury.id == row.treasury_id, Treasury.org_id == member.organization_id
            )
        )
        vendor = await session.scalar(
            select(Vendor).where(
                Vendor.id == payload.vendor_id, Vendor.org_id == member.organization_id
            )
        )
        payee = await session.scalar(
            select(Payee).where(
                Payee.id == payload.payee_id,
                Payee.vendor_id == payload.vendor_id,
                Payee.treasury_id == row.treasury_id,
            )
        )
        asset = await session.scalar(
            select(Asset).where(Asset.id == row.asset_id, Asset.chain_id == row.chain_id)
        )
        document = await session.scalar(
            select(RequestDocument).where(RequestDocument.request_id == row.id)
        )
        if (
            treasury is None
            or vendor is None
            or payee is None
            or asset is None
            or asset.address is None
            or document is None
        ):
            raise _fail(
                422,
                "EXTRACTION_FIELDS_INVALID",
                "Extracted fields invalid",
                "Choose a valid vendor, payee and payment asset.",
            )
        amount = _amount(payload.amount, asset.decimals)
        row.vendor_id, row.payee_id = vendor.id, payee.id
        row.invoice_no = payload.invoice_no
        row.issue_date, row.due_at, row.amount = payload.issue_date, payload.due_date, amount
        row.extraction_confirmed_by = member.user_id
        row.extraction_confirmed_at = datetime.now(UTC)
        row.last_edited_by = member.user_id
        row.current_revision += 1
        row.version += 1
        _hashes(row, vendor.normalized_ref, asset.address, document.sha256)
        session.add(
            RequestRevision(
                id=uuid7(),
                request_id=row.id,
                revision=row.current_revision,
                edited_by=member.user_id,
                snapshot={
                    "treasuryId": str(row.treasury_id),
                    "vendorId": str(vendor.id),
                    "payeeId": str(payee.id),
                    "invoiceNo": payload.invoice_no,
                    "issueDate": payload.issue_date.isoformat(),
                    "dueDate": payload.due_date.isoformat(),
                    "amount": str(amount),
                    "assetId": str(row.asset_id),
                },
                reason="operator confirmed extracted invoice fields",
            )
        )
        return {"requestId": str(row.id), "revision": row.current_revision, "confirmed": True}


@router.get(
    "/{request_id}/documents/{document_id}/url",
    openapi_extra={"x-organization-scoped": True},
)
async def document_read_url(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    member: MemberContext = Depends(require_member),  # noqa: B008
) -> DocumentUrlResponse:
    if organization_id != member.organization_id:
        raise _fail(
            404, "ORGANIZATION_NOT_FOUND", "Organization not found", "Organization not found."
        )
    async with _sessions(request)() as session:
        document = await session.scalar(
            select(RequestDocument)
            .join(PaymentRequest, PaymentRequest.id == RequestDocument.request_id)
            .where(
                PaymentRequest.id == request_id,
                PaymentRequest.org_id == member.organization_id,
                RequestDocument.id == document_id,
            )
        )
    if document is None:
        raise _fail(404, "DOCUMENT_NOT_FOUND", "Document not found", "Document not found.")
    url = await run_in_threadpool(_storage(request).sign_read, document.storage_key)
    return DocumentUrlResponse(url=url, expires_at=datetime.now(UTC) + PRESIGNED_URL_LIFETIME)


def _onchain_request_id(organization_id: uuid.UUID, request_id: uuid.UUID) -> bytes:
    from eth_abi import encode
    from eth_hash.auto import keccak

    return keccak(
        encode(
            ["string", "bytes16", "bytes16"], ["TP_REQ_V1", organization_id.bytes, request_id.bytes]
        )
    )
