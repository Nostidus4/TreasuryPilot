"""Authenticated email forwarding into the private invoice document pipeline."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import time
import unicodedata
import uuid
from datetime import datetime, timedelta
from email.utils import parseaddr
from io import BytesIO
from typing import cast

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import Field, field_validator, model_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.audit.models import AuditActorType
from treasurypilot_api.audit.writer import AuditActor, AuditEntity
from treasurypilot_api.audit.writer import write as write_audit
from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices import documents
from treasurypilot_api.invoices.models import (
    InvoiceInboundEmail,
    InvoiceInboundQuarantine,
    PaymentRequest,
    RequestDocument,
    RequestFlagSeverity,
    RequestFlagSource,
)
from treasurypilot_api.treasury.models import Treasury

router = APIRouter(tags=["invoice email intake"])
_require_org_admin = require_role(OrganizationRole.ORG_ADMIN)
SIGNATURE_HEADER = "X-TP-Email-Signature"
SIGNATURE_TOLERANCE_SECONDS = 5 * 60
MAX_WEBHOOK_BODY_BYTES = 15 * 1024 * 1024
MAX_EMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_EMAIL_ATTACHMENTS = 5
MAX_SENDER_ALLOWLIST = 100
MAX_UNTRUSTED_DISPLAY_CHARS = 320
# Dedupe ignores requests that can no longer be paid.
_DEAD_STATUSES = ("Rejected", "Cancelled", "Expired")
QUARANTINE_NOT_ALLOWLISTED = "SENDER_NOT_ALLOWLISTED"
QUARANTINE_UNAUTHENTICATED = "SENDER_UNAUTHENTICATED"


def clean_untrusted_text(value: str, limit: int = MAX_UNTRUSTED_DISPLAY_CHARS) -> str:
    """Strip control, zero-width and bidi characters and cap length.

    Everything in an email except its signed envelope is attacker-controlled. We only keep
    sender/filename for display and audit, never interpolate them into model prompts. Attachment
    bytes reach a model solely through the extraction worker, which wraps them with
    `wrap_untrusted` (the F-091 boundary); the email body is never read.
    """
    kept = "".join(ch for ch in value if unicodedata.category(ch) not in ("Cc", "Cf"))
    return kept.strip()[:limit]


def _fail(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


def _invalid_signature() -> AuthFailure:
    return _fail(
        401,
        "INBOUND_EMAIL_SIGNATURE_INVALID",
        "Email webhook authentication failed",
        "The email event signature is missing, invalid or expired.",
    )


async def _rate_limit(request: Request, local_part: str) -> None:
    limiter = getattr(request.app.state, "api_key_rate_limiter", None)
    try:
        if limiter is None:
            raise RuntimeError("rate limiter not configured")
        result = await limiter.hit(
            f"invoice-inbound-email:{local_part}", limit=60, window=timedelta(minutes=1)
        )
    except Exception:
        raise _fail(
            503,
            "RATE_LIMITER_UNAVAILABLE",
            "Service unavailable",
            "Request rate limiting is unavailable.",
        ) from None
    if not result.allowed:
        raise AuthFailure(
            status=429,
            code="RATE_LIMITED",
            title="Too many requests",
            detail="This inbound invoice address exceeded its rate limit.",
            retry_after=result.retry_after,
        )


def _sessions(request: Request) -> async_sessionmaker[AsyncSession]:
    sessions = getattr(request.app.state, "request_sessions", None)
    if sessions is None:
        raise _fail(
            503,
            "INBOUND_EMAIL_UNAVAILABLE",
            "Email intake unavailable",
            "Invoice email intake storage is not configured.",
        )
    return cast(async_sessionmaker[AsyncSession], sessions)


def _email_settings(request: Request) -> tuple[str, bytes]:
    settings = request.app.state.settings
    if not settings.inbound_email_configured:
        raise _fail(
            503,
            "INBOUND_EMAIL_UNAVAILABLE",
            "Email intake unavailable",
            "Configure the inbound email domain and a webhook secret of at least 32 bytes.",
        )
    secret = settings.inbound_email_webhook_secret.get_secret_value().encode()
    return cast(str, settings.inbound_email_domain), secret


def _signed_message(timestamp: str, body: bytes) -> bytes:
    return timestamp.encode("ascii") + b"." + body


def sign_webhook_body(secret: bytes, timestamp: int, body: bytes) -> str:
    """Create the webhook signature used by the configured mail provider adapter."""
    stamp = str(timestamp)
    digest = hmac.new(secret, _signed_message(stamp, body), hashlib.sha256).hexdigest()
    return f"t={stamp},v1={digest}"


def verify_webhook_signature(
    secret: bytes, body: bytes, signature: str | None, *, now: int | None = None
) -> bool:
    if signature is None:
        return False
    fields: dict[str, str] = {}
    for item in signature.split(","):
        key, separator, value = item.partition("=")
        key = key.strip()
        if not separator or key in fields:
            return False
        fields[key] = value
    timestamp, supplied = fields.get("t"), fields.get("v1")
    if timestamp is None or supplied is None or not (timestamp.isascii() and timestamp.isdigit()):
        return False
    try:
        parsed_timestamp = int(timestamp)
        supplied_bytes = bytes.fromhex(supplied)
    except ValueError:
        return False
    current = int(time.time()) if now is None else now
    if abs(current - parsed_timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret, _signed_message(timestamp, body), hashlib.sha256).digest()
    return hmac.compare_digest(expected, supplied_bytes)


def _normalize_allowlist_entry(value: str) -> str:
    entry = value.strip().casefold()
    if "@" in entry:
        domain = _sender_domain(entry)
        local = entry.rpartition("@")[0]
        if domain is None or not local or "@" in local or len(entry) > 320:
            raise ValueError("invalid sender address")
        return f"{local}@{domain}"
    domain = _canonical_domain(entry)
    if domain is None:
        raise ValueError("invalid sender domain")
    return domain


class InboundEmailConfiguration(ApiModel):
    treasury_id: uuid.UUID | None = None
    enabled: bool = True
    # Exact addresses or bare domains. Empty means no allowlist; None leaves it unchanged.
    sender_allowlist: list[str] | None = Field(default=None, max_length=MAX_SENDER_ALLOWLIST)

    @field_validator("sender_allowlist")
    @classmethod
    def normalize_allowlist(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return sorted({_normalize_allowlist_entry(item) for item in value})


class InboundEmailConfigurationView(ApiModel):
    enabled: bool
    treasury_id: uuid.UUID
    address: str
    sender_allowlist: list[str]


class QuarantinedEmailView(ApiModel):
    id: uuid.UUID
    reason: str
    sender: str
    sender_domain: str | None
    attachment_count: int
    evidence: dict[str, object]
    received_at: datetime


class QuarantinedEmailList(ApiModel):
    items: list[QuarantinedEmailView]


def _canonical_domain(value: str) -> str | None:
    try:
        domain = value.strip().rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError:
        return None
    labels = domain.split(".")
    if len(domain) > 253 or len(labels) < 2:
        return None
    if any(
        len(label) > 63 or re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label) is None
        for label in labels
    ):
        return None
    return domain


class SenderAuthentication(ApiModel):
    spf: str | None = Field(default=None, max_length=32)
    spf_domain: str | None = Field(default=None, max_length=253)
    dkim: str | None = Field(default=None, max_length=32)
    dkim_domain: str | None = Field(default=None, max_length=253)

    @field_validator("spf", "dkim")
    @classmethod
    def normalize_result(cls, value: str | None) -> str | None:
        return value.strip().casefold() if value else None

    @field_validator("spf_domain", "dkim_domain")
    @classmethod
    def normalize_domain(cls, value: str | None) -> str | None:
        return _canonical_domain(value) if value else None


class InboundEmailAttachment(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=4, max_length=MAX_WEBHOOK_BODY_BYTES)


class InboundEmailMessage(ApiModel):
    message_id: str = Field(min_length=1, max_length=998)
    sender: str = Field(min_length=3, max_length=320)
    recipient: str = Field(min_length=3, max_length=320)
    authentication_results: SenderAuthentication = Field(default_factory=SenderAuthentication)
    attachments: list[InboundEmailAttachment] = Field(max_length=MAX_EMAIL_ATTACHMENTS)

    @field_validator("message_id")
    @classmethod
    def normalize_message_id(cls, value: str) -> str:
        clean = value.strip()
        if not clean or any(ord(char) < 32 for char in clean):
            raise ValueError("invalid message ID")
        return clean

    @model_validator(mode="after")
    def require_attachments(self) -> InboundEmailMessage:
        if not self.attachments:
            raise ValueError("email must contain at least one supported invoice attachment")
        return self


class InboundEmailAttachmentReceipt(ApiModel):
    request_id: uuid.UUID
    document_id: uuid.UUID
    extraction_job_id: str


class InboundEmailReceipt(ApiModel):
    drafts: list[InboundEmailAttachmentReceipt]
    quarantined: bool = False
    duplicate_attachments: int = 0


def _sender_domain(sender: str) -> str | None:
    _, address = parseaddr(sender)
    local, separator, domain = address.rpartition("@")
    if not separator or not local or not domain or any(char.isspace() for char in address):
        return None
    return _canonical_domain(domain)


def _aligned(authenticated: str | None, sender_domain: str) -> bool:
    # Relaxed alignment (DMARC style). _canonical_domain already rejects bare TLDs.
    # shortcut: no public-suffix list, so a result for "co.uk" would align with "x.co.uk"; the
    # mail provider only reports domains it actually authenticated.
    return authenticated is not None and (
        authenticated == sender_domain or sender_domain.endswith("." + authenticated)
    )


def _sender_is_authenticated(message: InboundEmailMessage) -> bool:
    results = message.authentication_results
    sender_domain = _sender_domain(message.sender)
    if sender_domain is None:
        return False
    return (results.spf == "pass" and _aligned(results.spf_domain, sender_domain)) or (
        results.dkim == "pass" and _aligned(results.dkim_domain, sender_domain)
    )


def _sender_allowed(allowlist: list[str], sender: str) -> bool:
    _, address = parseaddr(sender)
    domain = _sender_domain(sender)
    if domain is None:
        return False
    return address.casefold() in allowlist or domain in allowlist


def _read_json(body: bytes) -> InboundEmailMessage:
    try:
        value = json.loads(body)
        return InboundEmailMessage.model_validate(value)
    except (json.JSONDecodeError, ValueError) as error:
        raise _fail(
            422,
            "INBOUND_EMAIL_INVALID",
            "Invalid email event",
            "The signed email event does not match the supported message format.",
        ) from error


@router.put(
    "/v1/orgs/{organization_id}/invoice-inbound-email",
    response_model=InboundEmailConfigurationView,
    openapi_extra={"x-organization-scoped": True},
)
async def configure_inbound_email(
    organization_id: uuid.UUID,
    payload: InboundEmailConfiguration,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> InboundEmailConfigurationView:
    domain, _ = _email_settings(request)
    factory = _sessions(request)
    async with factory() as session, session.begin():
        row = await session.get(InvoiceInboundEmail, organization_id)
        treasury_id = payload.treasury_id or (row.treasury_id if row else None)
        if payload.enabled and treasury_id is None:
            raise _fail(
                422,
                "TREASURY_REQUIRED",
                "Treasury required",
                "Select the treasury used for forwarded invoice drafts.",
            )
        if treasury_id is not None:
            treasury = await session.scalar(
                select(Treasury).where(
                    Treasury.id == treasury_id, Treasury.org_id == organization_id
                )
            )
            if treasury is None:
                raise _fail(404, "TREASURY_NOT_FOUND", "Treasury not found", "Treasury not found.")
        previous_allowlist = list(row.sender_allowlist) if row else []
        if row is None:
            if not payload.enabled:
                raise _fail(
                    404,
                    "INBOUND_EMAIL_NOT_CONFIGURED",
                    "Email intake not configured",
                    "Configure an inbound address before disabling it.",
                )
            # A concurrent first-time PUT may win the insert; keep its address and update it.
            await session.execute(
                pg_insert(InvoiceInboundEmail)
                .values(
                    org_id=organization_id,
                    treasury_id=cast(uuid.UUID, treasury_id),
                    local_part=secrets.token_hex(24),
                    enabled=True,
                    sender_allowlist=[],
                    created_by=member.user_id,
                )
                .on_conflict_do_nothing(index_elements=[InvoiceInboundEmail.org_id])
            )
            row = await session.scalar(
                select(InvoiceInboundEmail)
                .where(InvoiceInboundEmail.org_id == organization_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert row is not None
        if treasury_id is not None:
            row.treasury_id = treasury_id
        row.enabled = payload.enabled
        if payload.sender_allowlist is not None:
            row.sender_allowlist = payload.sender_allowlist

        await session.flush()
        await write_audit(
            session,
            org_id=organization_id,
            actor=AuditActor(AuditActorType.USER, member.user_id),
            action="invoice_inbound_email.configured",
            entity=AuditEntity("invoice_inbound_email", organization_id),
            data={
                "enabled": row.enabled,
                "treasuryId": str(row.treasury_id),
                "allowlistBefore": len(previous_allowlist),
                "allowlistAfter": len(row.sender_allowlist),
            },
        )
        view = _view(row, domain)

    return view


def _view(row: InvoiceInboundEmail, domain: str) -> InboundEmailConfigurationView:
    return InboundEmailConfigurationView(
        enabled=row.enabled,
        treasury_id=row.treasury_id,
        address=f"invoices+{row.local_part}@{domain}",
        sender_allowlist=list(row.sender_allowlist),
    )


@router.get(
    "/v1/orgs/{organization_id}/invoice-inbound-email",
    response_model=InboundEmailConfigurationView,
    openapi_extra={"x-organization-scoped": True},
)
async def get_inbound_email(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> InboundEmailConfigurationView:
    domain, _ = _email_settings(request)
    async with _sessions(request)() as session:
        row = await session.get(InvoiceInboundEmail, organization_id)
    if row is None:
        raise _fail(
            404,
            "INBOUND_EMAIL_NOT_CONFIGURED",
            "Email intake not configured",
            "No inbound invoice address is configured.",
        )
    return _view(row, domain)


@router.get(
    "/v1/orgs/{organization_id}/invoice-inbound-email/quarantine",
    response_model=QuarantinedEmailList,
    openapi_extra={"x-organization-scoped": True},
)
async def list_quarantined_emails(
    organization_id: uuid.UUID,
    request: Request,
    member: MemberAccess = Depends(_require_org_admin),  # noqa: B008
) -> QuarantinedEmailList:
    async with _sessions(request)() as session:
        rows = (
            await session.scalars(
                select(InvoiceInboundQuarantine)
                .where(InvoiceInboundQuarantine.org_id == organization_id)
                .order_by(InvoiceInboundQuarantine.received_at.desc())
                .limit(100)
            )
        ).all()
    return QuarantinedEmailList(
        items=[
            QuarantinedEmailView(
                id=row.id,
                reason=row.reason,
                sender=row.sender,
                sender_domain=row.sender_domain,
                attachment_count=row.attachment_count,
                evidence=row.evidence,
                received_at=row.received_at,
            )
            for row in rows
        ]
    )


@router.post(
    "/v1/inbound/invoices/{local_part}",
    status_code=202,
    response_model=InboundEmailReceipt,
)
async def receive_inbound_email(local_part: str, request: Request) -> InboundEmailReceipt:
    domain, secret = _email_settings(request)
    signature = request.headers.get(SIGNATURE_HEADER)
    if signature is None:  # cheap reject before buffering up to MAX_WEBHOOK_BODY_BYTES
        raise _invalid_signature()
    content_length = request.headers.get("content-length")
    if content_length is not None:
        try:
            if int(content_length) > MAX_WEBHOOK_BODY_BYTES:
                raise _fail(
                    413,
                    "INBOUND_EMAIL_TOO_LARGE",
                    "Email event too large",
                    "The email event exceeds the supported size.",
                )
        except ValueError as error:
            raise _fail(
                400, "INBOUND_EMAIL_INVALID", "Invalid email event", "Invalid content length."
            ) from error

    raw_body = bytearray()
    async for chunk in request.stream():
        raw_body.extend(chunk)
        if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
            raise _fail(
                413,
                "INBOUND_EMAIL_TOO_LARGE",
                "Email event too large",
                "The email event exceeds the supported size.",
            )
    body = bytes(raw_body)
    if not verify_webhook_signature(secret, body, signature):
        raise _invalid_signature()
    # After the signature check so only the mail provider can create limiter keys.
    await _rate_limit(request, local_part)
    message = _read_json(body)

    factory = _sessions(request)
    async with factory() as session:
        inbound = await session.scalar(
            select(InvoiceInboundEmail).where(
                InvoiceInboundEmail.local_part == local_part,
                InvoiceInboundEmail.enabled.is_(True),
            )
        )
    if inbound is None:
        raise _fail(
            404,
            "INBOUND_EMAIL_NOT_FOUND",
            "Email address not found",
            "This inbound invoice address is not enabled.",
        )
    expected_recipient = f"invoices+{local_part}@{domain}".casefold()
    actual_recipient = parseaddr(message.recipient)[1].casefold()
    if actual_recipient != expected_recipient:
        raise _fail(
            403,
            "INBOUND_EMAIL_RECIPIENT_MISMATCH",
            "Email recipient mismatch",
            "The signed message was addressed to a different inbound invoice address.",
        )

    decoded: list[tuple[str, bytes]] = []
    total_bytes = 0
    for attachment in message.attachments:
        filename = clean_untrusted_text(
            attachment.filename.replace("\\", "/").rsplit("/", 1)[-1], 255
        )
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise _fail(
                422,
                "INBOUND_EMAIL_ATTACHMENT_INVALID",
                "Invalid email attachment",
                "An attachment is not valid base64 data.",
            ) from error
        if not content:
            raise _fail(
                422,
                "INBOUND_EMAIL_ATTACHMENT_INVALID",
                "Invalid email attachment",
                "An attachment is empty.",
            )
        total_bytes += len(content)
        if total_bytes > MAX_EMAIL_ATTACHMENT_BYTES:
            raise _fail(
                413,
                "INBOUND_EMAIL_ATTACHMENT_TOO_LARGE",
                "Email attachments too large",
                "Email attachments must total no more than 10 MiB.",
            )
        decoded.append((filename, content))

    sender_verified = _sender_is_authenticated(message)
    sender_domain = _sender_domain(message.sender)
    message_digest = hashlib.sha256(message.message_id.encode()).hexdigest()
    auth_evidence: dict[str, object] = {
        "spf": message.authentication_results.spf or "missing",
        "spfDomain": message.authentication_results.spf_domain,
        "dkim": message.authentication_results.dkim or "missing",
        "dkimDomain": message.authentication_results.dkim_domain,
        "senderDomain": sender_domain,
    }
    allowlist = list(inbound.sender_allowlist)
    quarantine_reason: str | None = None
    if allowlist:
        if not _sender_allowed(allowlist, message.sender):
            quarantine_reason = QUARANTINE_NOT_ALLOWLISTED
        elif not sender_verified:
            quarantine_reason = QUARANTINE_UNAUTHENTICATED
    if quarantine_reason is not None:
        async with factory() as session, session.begin():
            inserted = await session.scalar(
                pg_insert(InvoiceInboundQuarantine)
                .values(
                    id=uuid.uuid4(),
                    org_id=inbound.org_id,
                    message_digest=message_digest,
                    reason=quarantine_reason,
                    sender=clean_untrusted_text(parseaddr(message.sender)[1] or message.sender),
                    sender_domain=sender_domain,
                    attachment_count=len(decoded),
                    evidence=auth_evidence,
                )
                .on_conflict_do_nothing(constraint="uq_invoice_inbound_quarantine_message")
                .returning(InvoiceInboundQuarantine.id)
            )
            if inserted is not None:  # a redelivery of the same message audits only once
                await write_audit(
                    session,
                    org_id=inbound.org_id,
                    actor=AuditActor(AuditActorType.SYSTEM),
                    action="invoice_inbound_email.quarantined",
                    entity=AuditEntity("invoice_inbound_email", inbound.org_id),
                    data={
                        "quarantineId": str(inserted),
                        "reason": quarantine_reason,
                        "senderDomain": sender_domain,
                        "attachmentCount": len(decoded),
                    },
                )
        return InboundEmailReceipt(drafts=[], quarantined=True)

    # Skip content already uploaded to this org (other messages or manual uploads) and repeats
    # inside this message. Same-message retries are excluded so they keep replaying.
    key_prefix = f"email:{inbound.org_id}:{message_digest}:"
    shas = {hashlib.sha256(content).digest() for _, content in decoded}
    async with factory() as session:
        known = set(
            (
                await session.scalars(
                    select(RequestDocument.sha256)
                    .join(
                        PaymentRequest,
                        and_(
                            PaymentRequest.id == RequestDocument.request_id,
                            PaymentRequest.org_id == inbound.org_id,
                        ),
                    )
                    .where(
                        RequestDocument.sha256.in_(shas),
                        PaymentRequest.status.notin_(_DEAD_STATUSES),
                        or_(
                            PaymentRequest.idempotency_key.is_(None),
                            PaymentRequest.idempotency_key.notlike(key_prefix + "%"),
                        ),
                    )
                )
            ).all()
        )
    seen = set(known)
    unique: list[tuple[int, str, bytes]] = []
    for index, (filename, content) in enumerate(decoded):
        digest = hashlib.sha256(content).digest()
        if digest in seen:
            continue
        seen.add(digest)
        unique.append((index, filename, content))
    duplicates = len(decoded) - len(unique)
    # Inspect every attachment before persisting any, so a bad one cannot leave partial drafts.
    inspected_documents = [
        (index, await documents.read_document(UploadFile(file=BytesIO(content), filename=filename)))
        for index, filename, content in unique
    ]
    receipts: list[InboundEmailAttachmentReceipt] = []
    for index, inspected in inspected_documents:
        result = await documents.create_invoice_document_draft(
            request=request,
            organization_id=inbound.org_id,
            treasury_id=inbound.treasury_id,
            document=inspected,
            idempotency_key=f"email:{inbound.org_id}:{message_digest}:{index}",
            bind_treasury=False,
            uploaded_by=None,
            initial_flags=(
                documents.InitialRequestFlag(
                    code="INBOUND_EMAIL_SENDER_UNVERIFIED",
                    severity=RequestFlagSeverity.HIGH,
                    evidence=auth_evidence,
                    source=RequestFlagSource.DETERMINISTIC,
                ),
            )
            if not sender_verified
            else (),
        )
        receipts.append(
            InboundEmailAttachmentReceipt(
                request_id=result.request_id,
                document_id=result.document_id,
                extraction_job_id=result.extraction_job_id,
            )
        )

    async with factory() as session, session.begin():
        await write_audit(
            session,
            org_id=inbound.org_id,
            actor=AuditActor(AuditActorType.SYSTEM),
            action="invoice_inbound_email.received",
            entity=AuditEntity("invoice_inbound_email", inbound.org_id),
            data={
                "messageDigest": message_digest,
                "senderDomain": sender_domain,
                "senderVerified": sender_verified,
                "draftRequestIds": [str(item.request_id) for item in receipts],
                "duplicateAttachments": duplicates,
            },
        )
    # No approval record or state transition is created by this integration. Every result is a
    # normal upload draft and remains subject to the existing human extraction/review workflow.
    return InboundEmailReceipt(drafts=receipts, duplicate_attachments=duplicates)
