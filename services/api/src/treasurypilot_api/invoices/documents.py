"""Private invoice document storage and upload-to-extraction handoff (INV-004)."""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.concurrency import run_in_threadpool

from treasurypilot_api.agent.models import Extraction
from treasurypilot_api.config import Settings
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_member, require_role
from treasurypilot_api.invoices.fingerprints import (
    DuplicateFingerprintConflict,
    find_active_duplicate,
)
from treasurypilot_api.invoices.models import (
    ExtractionStatus,
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
from treasurypilot_api.invoices.requests import (
    _amount,
    _bound_fields,
    _fail,
    _hashes,
    _raise_if_fingerprint_race,
    _recompute_flags,
    _request_id,
    _sessions,
    _validate_dates,
    supersede_open_flags,
)
from treasurypilot_api.treasury.models import Asset, Treasury

router = APIRouter(prefix="/v1/orgs/{organization_id}/requests", tags=["invoice documents"])
_require_operator = require_role(OrganizationRole.OPERATOR, OrganizationRole.ORG_ADMIN)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_PAGES = 20
MAX_IMAGE_PIXELS = 40_000_000
logger = logging.getLogger(__name__)
PRESIGNED_URL_LIFETIME = timedelta(minutes=5)
EXTRACTION_TASK = "treasurypilot.invoices.extract_document"


class ObjectStorage(Protocol):
    def put(self, object_key: str, body: bytes, content_type: str) -> None: ...

    def sign_read(self, object_key: str) -> str: ...

    def delete(self, object_key: str) -> None: ...


class ExtractionQueue(Protocol):
    def enqueue(self, request_id: uuid.UUID, document_id: uuid.UUID, job_id: str) -> str: ...


@dataclass(frozen=True)
class InitialRequestFlag:
    """A deterministic risk flag to commit atomically with a newly uploaded draft."""

    code: str
    severity: RequestFlagSeverity
    evidence: dict[str, object]
    source: RequestFlagSource


class MinioObjectStorage:
    """S3-compatible storage adapter; buckets remain private by default."""

    def __init__(self, client: Minio, bucket: str, signing_client: Minio | None = None) -> None:
        self.client = client
        self.bucket = bucket
        # Presigned URLs embed the host, so sign with the browser-reachable endpoint.
        self.signing_client = signing_client or client

    def put(self, object_key: str, body: bytes, content_type: str) -> None:
        self.client.put_object(
            self.bucket,
            object_key,
            BytesIO(body),
            length=len(body),
            content_type=content_type,
        )

    def sign_read(self, object_key: str) -> str:
        return self.signing_client.presigned_get_object(
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
        # Partial config disables uploads (503 on use) instead of taking the whole API down.
        logger.warning(
            "Document storage disabled: S3_ENDPOINT_URL, S3_BUCKET, S3_ACCESS_KEY and "
            "S3_SECRET_KEY must all be set"
        )
        return None

    def client_for(url: str, region: str | None = None) -> Minio:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname is None:
            raise ValueError("S3 endpoint URLs must be http(s) URLs")
        return Minio(
            parsed.netloc,
            access_key=cast(object, settings.s3_access_key).get_secret_value(),  # type: ignore[attr-defined]
            secret_key=cast(object, settings.s3_secret_key).get_secret_value(),  # type: ignore[attr-defined]
            secure=parsed.scheme == "https",
            region=region,
        )

    client = client_for(cast(str, settings.s3_endpoint_url))
    # An explicit region lets the signing client presign offline (no bucket-location lookup).
    signing = (
        client_for(settings.s3_public_endpoint_url, "us-east-1")
        if settings.s3_public_endpoint_url
        else None
    )
    return MinioObjectStorage(client, cast(str, settings.s3_bucket), signing)


def build_extraction_queue(settings: Settings) -> ExtractionQueue | None:
    if settings.redis_url is None:
        return None
    return CeleryExtractionQueue(settings.redis_url.get_secret_value())


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


def _inspect_document(body: bytes, filename: str) -> tuple[str, int]:
    """CPU-bound parsing; run in a worker thread. Raises on any invalid document."""
    if body.startswith(b"%PDF-") and filename.endswith(".pdf"):
        reader = PdfReader(BytesIO(body), strict=True)
        if reader.is_encrypted:
            raise ValueError("Encrypted PDFs are not supported")
        return "application/pdf", len(reader.pages)
    for signature, suffixes, image_format, mime in (
        (b"\x89PNG\r\n\x1a\n", (".png",), "PNG", "image/png"),
        (b"\xff\xd8\xff", (".jpg", ".jpeg"), "JPEG", "image/jpeg"),
    ):
        if body.startswith(signature) and filename.endswith(suffixes):
            with Image.open(BytesIO(body)) as image:
                if image.format != image_format:
                    raise ValueError(f"{image_format} signature does not match image format")
                if image.width * image.height > MAX_IMAGE_PIXELS:
                    raise ValueError("Image dimensions are too large")
                image.verify()
            return mime, 1
    raise ValueError("File content or extension is not a supported PDF, PNG or JPEG")


async def read_document(file: UploadFile) -> tuple[bytes, str, int]:
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
    try:
        mime, pages = await run_in_threadpool(
            _inspect_document, body, (file.filename or "").lower()
        )
    except Exception as error:
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


async def _previous_upload(
    factory: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    idempotency_key: str,
    payload_hash: bytes,
) -> tuple[PaymentRequest, RequestDocument] | None:
    async with factory() as session:
        previous = await session.scalar(
            select(PaymentRequest).where(
                PaymentRequest.org_id == organization_id,
                PaymentRequest.idempotency_key == idempotency_key,
            )
        )
        if previous is None:
            return None
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
    return previous, document


async def create_invoice_document_draft(
    *,
    request: Request,
    organization_id: uuid.UUID,
    treasury_id: uuid.UUID,
    document: tuple[bytes, str, int],
    idempotency_key: str,
    uploaded_by: uuid.UUID | None,
    initial_flags: tuple[InitialRequestFlag, ...] = (),
    bind_treasury: bool = True,
) -> UploadResponse:
    """Store an already-inspected document and enqueue the existing extraction path."""
    body, mime, pages = document
    digest = hashlib.sha256(body).digest()
    storage = _storage(request)
    queue = _queue(request)
    factory = _sessions(request)

    async with factory() as session:
        treasury = await session.scalar(
            select(Treasury).where(Treasury.id == treasury_id, Treasury.org_id == organization_id)
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

    # Email retries must replay even if the org re-pointed its intake treasury meanwhile.
    payload_hash = hashlib.sha256((treasury_id.bytes if bind_treasury else b"") + digest).digest()
    replay = await _previous_upload(factory, organization_id, idempotency_key, payload_hash)
    if replay is None:
        request_id, document_id = uuid7(), uuid7()
        object_key = f"organizations/{organization_id}/requests/{request_id}/{document_id}"
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
            org_id=organization_id,
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
            extraction_status=ExtractionStatus.EXTRACTING.value,
            status=RequestStatus.DRAFT.value,
            current_revision=1,
            created_by=uploaded_by,
            last_edited_by=uploaded_by,
            onchain_request_id=_request_id(organization_id, request_id),
            idempotency_key=idempotency_key,
            idempotency_payload_hash=payload_hash,
        )
        revision = RequestRevision(
            id=uuid7(),
            request_id=request_id,
            revision=1,
            edited_by=uploaded_by,
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
        document_row = RequestDocument(
            id=document_id,
            request_id=request_id,
            storage_key=object_key,
            sha256=digest,
            mime=mime,
            size=len(body),
            pages=pages,
            uploaded_by=uploaded_by,
        )
        try:
            async with factory() as write_session, write_session.begin():
                write_session.add_all([row, revision, document_row])
                # RequestFlag has a composite FK to RequestRevision. Flush these parents first;
                # SQLAlchemy cannot infer their order without mapped ORM relationships.
                await write_session.flush()
                write_session.add_all(
                    RequestFlag(
                        id=uuid7(),
                        request_id=request_id,
                        revision=1,
                        code=flag.code,
                        severity=flag.severity.value,
                        evidence=flag.evidence,
                        source=flag.source.value,
                        status=RequestFlagStatus.OPEN.value,
                    )
                    for flag in initial_flags
                )
        except Exception as error:
            try:
                await run_in_threadpool(storage.delete, object_key)
            except Exception:
                # An object may stay orphaned; a periodic reconciliation job can remove it.
                logger.exception("Failed to delete orphaned document %s", object_key)
            if not isinstance(error, IntegrityError):
                raise
            # A concurrent upload with the same key won the race: treat it as a replay.
            replay = await _previous_upload(factory, organization_id, idempotency_key, payload_hash)
            if replay is None:
                raise
    confirmed = False
    if replay is not None:
        previous, document_row = replay
        request_id, document_id = previous.id, document_row.id
        confirmed = previous.extraction_confirmed_at is not None

    job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"treasurypilot:invoice-extract:{request_id}").hex
    if confirmed:  # replay after confirmation must not re-run extraction
        return UploadResponse(
            request_id=request_id, document_id=document_id, extraction_job_id=job_id
        )
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


@router.post("/upload", status_code=202, openapi_extra={"x-organization-scoped": True})
async def upload_invoice_document(
    organization_id: uuid.UUID,
    request: Request,
    treasury_id: uuid.UUID = Form(),  # noqa: B008
    file: UploadFile = File(),  # noqa: B008
    idempotency_key: str | None = Header(
        default=None, alias="Idempotency-Key", min_length=1, max_length=255
    ),
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> UploadResponse:
    if idempotency_key is None:
        raise _fail(
            400,
            "IDEMPOTENCY_KEY_REQUIRED",
            "Idempotency key required",
            "Provide an Idempotency-Key for this upload.",
        )
    body, mime, pages = await read_document(file)
    return await create_invoice_document_draft(
        request=request,
        organization_id=member.organization_id,
        treasury_id=treasury_id,
        document=(body, mime, pages),
        idempotency_key=idempotency_key,
        uploaded_by=member.user_id,
    )


@router.post("/{request_id}/extraction/confirm", openapi_extra={"x-organization-scoped": True})
async def confirm_extraction(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: ExtractionConfirmation,
    request: Request,
    member: MemberAccess = Depends(_require_operator),  # noqa: B008
) -> dict[str, object]:
    """Apply operator-reviewed extraction fields to the current upload draft."""
    _validate_dates(payload.issue_date, payload.due_date)
    factory = _sessions(request)
    scope: tuple[uuid.UUID, bytes] | None = None
    try:
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
            if row.source != RequestSource.UPLOAD.value or row.status != RequestStatus.DRAFT.value:
                raise _fail(
                    409,
                    "REQUEST_NOT_EDITABLE",
                    "Request not editable",
                    "Only upload drafts can be confirmed.",
                )
            if row.extraction_status == ExtractionStatus.EXTRACTING.value:
                raise _fail(
                    409,
                    "EXTRACTION_PENDING",
                    "Extraction pending",
                    "The document is still being extracted; confirm once it settles.",
                )
            document = await session.scalar(
                select(RequestDocument)
                .where(RequestDocument.request_id == row.id)
                .order_by(RequestDocument.created_at.desc(), RequestDocument.id.desc())
                .limit(1)
            )
            extraction = (
                await session.scalar(
                    select(Extraction).where(Extraction.document_id == document.id)
                )
                if document is not None
                else None
            )
            stored = extraction.fields.get("invoice_count_in_document") if extraction else None
            # A malformed stored count is ignored so the operator's own report still decides.
            if isinstance(stored, int) and not isinstance(stored, bool) and stored >= 1:
                reported_count = max(stored, payload.invoice_count_in_document)
            else:
                reported_count = payload.invoice_count_in_document
            if reported_count > 1:
                open_flag = await session.scalar(
                    select(RequestFlag.id)
                    .where(
                        RequestFlag.request_id == row.id,
                        RequestFlag.code == "MULTI_INVOICE_DOCUMENT",
                        RequestFlag.status == RequestFlagStatus.OPEN.value,
                    )
                    .limit(1)
                )
                if open_flag is None:
                    session.add(
                        RequestFlag(
                            id=uuid7(),
                            request_id=row.id,
                            revision=row.current_revision,
                            code="MULTI_INVOICE_DOCUMENT",
                            severity=RequestFlagSeverity.HIGH.value,
                            evidence={"invoiceCountInDocument": reported_count},
                            source=RequestFlagSource.AI.value,
                            status=RequestFlagStatus.OPEN.value,
                        )
                    )
            else:
                _treasury, vendor, _payee, asset = await _bound_fields(
                    session,
                    organization_id=member.organization_id,
                    treasury_id=row.treasury_id,
                    vendor_id=payload.vendor_id,
                    payee_id=payload.payee_id,
                    asset_id=row.asset_id,
                    paying_wallet_id=None,
                )
                if document is None:
                    raise _fail(
                        422,
                        "EXTRACTION_FIELDS_INVALID",
                        "Extracted fields invalid",
                        "The uploaded document is unavailable.",
                    )
                amount = _amount(payload.amount, asset.decimals)
                row.vendor_id, row.payee_id = vendor.id, payload.payee_id
                row.invoice_no = payload.invoice_no
                row.issue_date, row.due_at, row.amount = (
                    payload.issue_date,
                    payload.due_date,
                    amount,
                )
                row.extraction_confirmed_by = member.user_id
                row.extraction_confirmed_at = datetime.now(UTC)
                row.last_edited_by = member.user_id
                row.current_revision += 1
                row.version += 1
                scope = (
                    row.treasury_id,
                    _hashes(
                        row, vendor.normalized_ref, cast(bytes, asset.address), document.sha256
                    ),
                )
                duplicate = await find_active_duplicate(
                    session, treasury_id=scope[0], value=scope[1], exclude_request_id=row.id
                )
                if duplicate is not None:
                    raise DuplicateFingerprintConflict(duplicate)
                session.add(
                    RequestRevision(
                        id=uuid7(),
                        request_id=row.id,
                        revision=row.current_revision,
                        edited_by=member.user_id,
                        snapshot={
                            "treasuryId": str(row.treasury_id),
                            "vendorId": str(vendor.id),
                            "payeeId": str(payload.payee_id),
                            "invoiceNo": payload.invoice_no,
                            "issueDate": payload.issue_date.isoformat(),
                            "dueDate": payload.due_date.isoformat(),
                            "amount": str(amount),
                            "assetId": str(row.asset_id),
                        },
                        reason="operator confirmed extracted invoice fields",
                    )
                )
                await supersede_open_flags(session, row, keep=("MULTI_INVOICE_DOCUMENT",))
                flags = await _recompute_flags(session, row)
                return {
                    "requestId": str(row.id),
                    "revision": row.current_revision,
                    "confirmed": True,
                    "flags": flags,
                }
    except IntegrityError as error:
        # Concurrent confirm of the same invoice lost the uq_payment_requests_active_fingerprint race.
        await _raise_if_fingerprint_race(factory, error, scope, request_id)
        raise
    raise _fail(
        422,
        "MULTI_INVOICE_DOCUMENT",
        "Multiple invoices detected",
        "Upload one invoice per document; this extraction cannot be confirmed.",
    )


@router.get(
    "/{request_id}/documents/{document_id}/url",
    openapi_extra={"x-organization-scoped": True},
)
async def document_read_url(
    organization_id: uuid.UUID,
    request_id: uuid.UUID,
    document_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(require_member),  # noqa: B008
) -> DocumentUrlResponse:
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
    signed_at = datetime.now(UTC)
    url = await run_in_threadpool(_storage(request).sign_read, document.storage_key)
    return DocumentUrlResponse(url=url, expires_at=signed_at + PRESIGNED_URL_LIFETIME)
