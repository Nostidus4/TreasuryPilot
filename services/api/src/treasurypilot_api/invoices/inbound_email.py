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
import uuid
from email.utils import parseaddr
from io import BytesIO
from typing import cast

from fastapi import APIRouter, Depends, Request, UploadFile
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.identity.models import OrganizationRole, uuid7
from treasurypilot_api.identity.rbac import MemberAccess, require_role
from treasurypilot_api.invoices import documents
from treasurypilot_api.invoices.models import (
    InvoiceInboundEmail,
    RequestFlag,
    RequestFlagSeverity,
    RequestFlagSource,
    RequestFlagStatus,
)
from treasurypilot_api.treasury.models import Treasury

router = APIRouter(tags=["invoice email intake"])
_require_org_admin = require_role(OrganizationRole.ORG_ADMIN)
SIGNATURE_HEADER = "X-TP-Email-Signature"
SIGNATURE_TOLERANCE_SECONDS = 5 * 60
MAX_WEBHOOK_BODY_BYTES = 15 * 1024 * 1024
MAX_EMAIL_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_EMAIL_ATTACHMENTS = 5


def _fail(status: int, code: str, title: str, detail: str) -> AuthFailure:
    return AuthFailure(status=status, code=code, title=title, detail=detail)


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
        if not separator or key in fields:
            return False
        fields[key.strip()] = value.strip()
    timestamp, supplied = fields.get("t"), fields.get("v1")
    if timestamp is None or supplied is None:
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


class InboundEmailConfiguration(ApiModel):
    treasury_id: uuid.UUID | None = None
    enabled: bool = True


class InboundEmailConfigurationView(ApiModel):
    enabled: bool
    treasury_id: uuid.UUID
    address: str


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


def _sender_domain(sender: str) -> str | None:
    _, address = parseaddr(sender)
    local, separator, domain = address.rpartition("@")
    if not separator or not local or not domain or any(char.isspace() for char in address):
        return None
    return _canonical_domain(domain)


def _sender_is_authenticated(message: InboundEmailMessage) -> bool:
    results = message.authentication_results
    sender_domain = _sender_domain(message.sender)
    if sender_domain is None:
        return False
    return (results.spf == "pass" and results.spf_domain == sender_domain) or (
        results.dkim == "pass" and results.dkim_domain == sender_domain
    )


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
        if row is None:
            if not payload.enabled:
                raise _fail(
                    404,
                    "INBOUND_EMAIL_NOT_CONFIGURED",
                    "Email intake not configured",
                    "Configure an inbound address before disabling it.",
                )
            row = InvoiceInboundEmail(
                org_id=organization_id,
                treasury_id=cast(uuid.UUID, treasury_id),
                local_part=secrets.token_hex(24),
                enabled=True,
                created_by=member.user_id,
            )
            session.add(row)
        else:
            if treasury_id is not None:
                row.treasury_id = treasury_id
            row.enabled = payload.enabled

        await session.flush()
        local_part = row.local_part
        configured_treasury_id = row.treasury_id
        enabled = row.enabled

    return InboundEmailConfigurationView(
        enabled=enabled,
        treasury_id=configured_treasury_id,
        address=f"invoices+{local_part}@{domain}",
    )


@router.post(
    "/v1/inbound/invoices/{local_part}",
    status_code=202,
    response_model=InboundEmailReceipt,
)
async def receive_inbound_email(local_part: str, request: Request) -> InboundEmailReceipt:
    domain, secret = _email_settings(request)
    signature = request.headers.get(SIGNATURE_HEADER)
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
        raise _fail(
            401,
            "INBOUND_EMAIL_SIGNATURE_INVALID",
            "Email webhook authentication failed",
            "The email event signature is missing, invalid or expired.",
        )
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
        filename = attachment.filename.replace("\\", "/").rsplit("/", 1)[-1]
        try:
            content = base64.b64decode(attachment.content_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            raise _fail(
                422,
                "INBOUND_EMAIL_ATTACHMENT_INVALID",
                "Invalid email attachment",
                "An attachment is not valid base64 data.",
            ) from error
        total_bytes += len(content)
        if not content or total_bytes > MAX_EMAIL_ATTACHMENT_BYTES:
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
    receipts: list[InboundEmailAttachmentReceipt] = []
    for index, (filename, content) in enumerate(decoded):
        upload = UploadFile(file=BytesIO(content), filename=filename)
        inspected = await documents._read_document(upload)
        result = await documents.create_invoice_document_draft(
            request=request,
            organization_id=inbound.org_id,
            treasury_id=inbound.treasury_id,
            document=inspected,
            idempotency_key=f"email-{message_digest}-{index}",
            uploaded_by=None,
        )
        if not sender_verified:
            async with factory() as session, session.begin():
                existing_flag = await session.scalar(
                    select(RequestFlag).where(
                        RequestFlag.request_id == result.request_id,
                        RequestFlag.revision == 1,
                        RequestFlag.code == "INBOUND_EMAIL_SENDER_UNVERIFIED",
                    )
                )
                if existing_flag is None:
                    session.add(
                        RequestFlag(
                            id=uuid7(),
                            request_id=result.request_id,
                            revision=1,
                            code="INBOUND_EMAIL_SENDER_UNVERIFIED",
                            severity=RequestFlagSeverity.HIGH.value,
                            evidence={
                                "spf": message.authentication_results.spf or "missing",
                                "spfDomain": message.authentication_results.spf_domain,
                                "dkim": message.authentication_results.dkim or "missing",
                                "dkimDomain": message.authentication_results.dkim_domain,
                                "senderDomain": sender_domain,
                            },
                            source=RequestFlagSource.DETERMINISTIC.value,
                            status=RequestFlagStatus.OPEN.value,
                        )
                    )
        receipts.append(
            InboundEmailAttachmentReceipt(
                request_id=result.request_id,
                document_id=result.document_id,
                extraction_job_id=result.extraction_job_id,
            )
        )

    # No approval record or state transition is created by this integration. Every result is a
    # normal upload draft and remains subject to the existing human extraction/review workflow.
    return InboundEmailReceipt(drafts=receipts)
