"""Telegram linking: one-time codes, the bot webhook and channel preferences.

The bot is a notification channel only. The webhook understands exactly one command
(``/start <code>``, which links a chat); nothing received from Telegram can approve,
sign or pay (M13-D6).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol, cast

from fastapi import APIRouter, Request
from pydantic import Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from treasurypilot_api.identity.api import ApiModel, _authenticated
from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.notifications.models import (
    ChannelKind,
    NotificationChannel,
    TelegramLinkCode,
)
from treasurypilot_core.privacy import FieldCipher

logger = logging.getLogger(__name__)

WEBHOOK_SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
LINK_CODE_TTL = timedelta(minutes=10)
# Encryption context binds the envelope to this column (see FieldCipher.encrypt).
TARGET_CONTEXT = "notification_channels.target"

LINKED_REPLY = (
    "TreasuryPilot is linked. You will get notifications here. "
    "Approvals, signatures and payments can only be done in the app."
)
INVALID_CODE_REPLY = "This link code is invalid or expired. Create a new one in TreasuryPilot."
CHAT_TAKEN_REPLY = "This Telegram chat is already linked to another TreasuryPilot account."


class TelegramUnavailable(Exception):
    """Linking is not configured (bot username or field encryption key missing)."""


class WebhookAlreadyLinked(Exception):
    """An incoming webhook destination already belongs to another account."""


class LinkOutcome:
    LINKED = "linked"
    INVALID_CODE = "invalid_code"
    CHAT_TAKEN = "chat_taken"


class LinkCodeIssued(ApiModel):
    code: str
    bot_url: str
    expires_at: datetime


class ChannelView(ApiModel):
    id: uuid.UUID
    kind: ChannelKind
    active: bool
    show_amounts: bool
    verified_at: datetime

    @classmethod
    def from_channel(cls, channel: NotificationChannel) -> ChannelView:
        return cls(
            id=channel.id,
            kind=ChannelKind(channel.kind),
            active=channel.active,
            show_amounts=channel.show_amounts,
            verified_at=channel.verified_at,
        )


class ChannelList(ApiModel):
    items: list[ChannelView]


class ChannelPatch(ApiModel):
    show_amounts: bool = Field(alias="showAmounts")


class WebhookChannelCreate(ApiModel):
    webhook_url: str = Field(alias="webhookUrl", min_length=1, max_length=2048)


class TelegramRepository(Protocol):
    async def issue_link_code(self, *, user_id: uuid.UUID) -> tuple[str, datetime]: ...

    async def complete_link(self, *, code: str, chat_id: int) -> str: ...

    async def list_channels(self, *, user_id: uuid.UUID) -> tuple[NotificationChannel, ...]: ...

    async def set_show_amounts(
        self, *, user_id: uuid.UUID, channel_id: uuid.UUID, show_amounts: bool
    ) -> NotificationChannel | None: ...

    async def unlink(self, *, user_id: uuid.UUID, channel_id: uuid.UUID) -> bool: ...

    async def connect_chat(
        self, *, user_id: uuid.UUID, kind: ChannelKind, webhook_url: str
    ) -> NotificationChannel: ...


def hash_link_code(code: str) -> bytes:
    return hashlib.sha256(code.encode()).digest()


class SqlAlchemyTelegramRepository:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        cipher: FieldCipher | None,
        hash_key: bytes,
        now: Any = None,
    ) -> None:
        self._sessions = sessions
        self._cipher = cipher
        self._hash_key = hash_key
        self._now = now or (lambda: datetime.now(UTC))

    def _chat_hash(self, chat_id: int) -> bytes:
        # Keyed: Telegram chat ids are small integers and must not be recoverable
        # from a leaked hash column.
        return hmac.new(self._hash_key, f"telegram:{chat_id}".encode(), hashlib.sha256).digest()

    @staticmethod
    def _validate_chat_webhook(kind: ChannelKind, value: str) -> None:
        parsed = urllib.parse.urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("invalid webhook URL")
        host, path = parsed.hostname.casefold(), parsed.path
        if kind is ChannelKind.SLACK:
            valid = host == "hooks.slack.com" and path.startswith("/services/")
        elif kind is ChannelKind.LARK:
            valid = host in {"open.larksuite.com", "open.feishu.cn"} and path.startswith(
                "/open-apis/bot/v2/hook/"
            )
        elif kind is ChannelKind.WECOM:
            valid = host == "qyapi.weixin.qq.com" and path == "/cgi-bin/webhook/send"
        else:
            valid = False
        if not valid:
            raise ValueError("invalid webhook URL")

    async def connect_chat(
        self, *, user_id: uuid.UUID, kind: ChannelKind, webhook_url: str
    ) -> NotificationChannel:
        if kind is ChannelKind.TELEGRAM or self._cipher is None:
            raise TelegramUnavailable
        self._validate_chat_webhook(kind, webhook_url)
        now = self._now()
        values = {
            "target": self._cipher.encrypt_text(webhook_url, context=TARGET_CONTEXT),
            "target_hash": hmac.new(
                self._hash_key, f"{kind.value}:{webhook_url}".encode(), hashlib.sha256
            ).digest(),
            "verified_at": now,
            "active": True,
            "last_sent_at": None,
        }
        try:
            async with self._sessions() as session, session.begin():
                statement = insert(NotificationChannel).values(
                    id=uuid.uuid4(), user_id=user_id, kind=kind.value, **values
                )
                row = await session.scalar(
                    statement.on_conflict_do_update(
                        constraint="uq_notification_channels_user_kind", set_=values
                    ).returning(NotificationChannel)
                )
                assert row is not None
                return row
        except IntegrityError as exc:
            raise WebhookAlreadyLinked from exc

    async def issue_link_code(self, *, user_id: uuid.UUID) -> tuple[str, datetime]:
        now = self._now()
        code = secrets.token_urlsafe(16)  # 128 bits; fits Telegram's start-parameter alphabet
        expires_at = now + LINK_CODE_TTL
        async with self._sessions() as session, session.begin():
            # A user holds at most one live code: a new one replaces older unused ones.
            await session.execute(
                delete(TelegramLinkCode).where(
                    TelegramLinkCode.user_id == user_id,
                    (TelegramLinkCode.used_at.is_(None)) | (TelegramLinkCode.expires_at <= now),
                )
            )
            session.add(
                TelegramLinkCode(
                    code_hash=hash_link_code(code), user_id=user_id, expires_at=expires_at
                )
            )
        return code, expires_at

    async def complete_link(self, *, code: str, chat_id: int) -> str:
        if self._cipher is None:
            raise TelegramUnavailable
        now = self._now()
        try:
            async with self._sessions() as session, session.begin():
                # Atomic single use: the UPDATE only matches an unused, unexpired code.
                user_id = await session.scalar(
                    update(TelegramLinkCode)
                    .where(
                        TelegramLinkCode.code_hash == hash_link_code(code),
                        TelegramLinkCode.used_at.is_(None),
                        TelegramLinkCode.expires_at > now,
                    )
                    .values(used_at=now)
                    .returning(TelegramLinkCode.user_id)
                )
                if user_id is None:
                    return LinkOutcome.INVALID_CODE
                values = {
                    "target": self._cipher.encrypt_text(str(chat_id), context=TARGET_CONTEXT),
                    "target_hash": self._chat_hash(chat_id),
                    "verified_at": now,
                    "active": True,
                    "last_sent_at": None,
                }
                statement = insert(NotificationChannel).values(
                    id=uuid.uuid4(), user_id=user_id, kind=ChannelKind.TELEGRAM.value, **values
                )
                await session.execute(
                    statement.on_conflict_do_update(
                        constraint="uq_notification_channels_user_kind", set_=values
                    )
                )
        except IntegrityError:
            # The chat is already linked to a different user; the transaction rolled
            # back, so the code was not consumed.
            return LinkOutcome.CHAT_TAKEN
        return LinkOutcome.LINKED

    async def list_channels(self, *, user_id: uuid.UUID) -> tuple[NotificationChannel, ...]:
        async with self._sessions() as session:
            rows = await session.scalars(
                select(NotificationChannel)
                .where(NotificationChannel.user_id == user_id)
                .order_by(NotificationChannel.created_at)
            )
            return tuple(rows)

    async def set_show_amounts(
        self, *, user_id: uuid.UUID, channel_id: uuid.UUID, show_amounts: bool
    ) -> NotificationChannel | None:
        async with self._sessions() as session, session.begin():
            return await session.scalar(
                update(NotificationChannel)
                .where(NotificationChannel.id == channel_id, NotificationChannel.user_id == user_id)
                .values(show_amounts=show_amounts)
                .returning(NotificationChannel)
            )

    async def unlink(self, *, user_id: uuid.UUID, channel_id: uuid.UUID) -> bool:
        async with self._sessions() as session, session.begin():
            deleted = await session.scalar(
                delete(NotificationChannel)
                .where(NotificationChannel.id == channel_id, NotificationChannel.user_id == user_id)
                .returning(NotificationChannel.id)
            )
            return deleted is not None


def _repository(request: Request) -> TelegramRepository:
    repository = getattr(request.app.state, "telegram_repository", None)
    if repository is None:
        raise _unavailable()
    return cast(TelegramRepository, repository)


def _unavailable() -> AuthFailure:
    return AuthFailure(
        status=503,
        code="TELEGRAM_UNAVAILABLE",
        title="Telegram unavailable",
        detail="Telegram notifications are not configured.",
    )


def _channel_not_found() -> AuthFailure:
    return AuthFailure(
        status=404,
        code="CHANNEL_NOT_FOUND",
        title="Channel not found",
        detail="The notification channel does not exist or is not yours.",
    )


router = APIRouter(prefix="/v1", tags=["notifications"])


@router.post("/me/channels/telegram/link-code", response_model=LinkCodeIssued)
async def create_link_code(request: Request) -> LinkCodeIssued:
    access = await _authenticated(request, require_csrf=True)
    username = request.app.state.settings.telegram_bot_username
    if not username:
        raise _unavailable()
    try:
        code, expires_at = await _repository(request).issue_link_code(user_id=access.user.id)
    except TelegramUnavailable as exc:
        raise _unavailable() from exc
    return LinkCodeIssued(
        code=code, bot_url=f"https://t.me/{username}?start={code}", expires_at=expires_at
    )


@router.post("/me/channels/{kind}", response_model=ChannelView)
async def connect_chat_channel(
    kind: Literal["slack", "lark", "wecom"],
    payload: WebhookChannelCreate,
    request: Request,
) -> ChannelView:
    channel_kind = ChannelKind(kind.upper())
    access = await _authenticated(request, require_csrf=True)
    try:
        channel = await _repository(request).connect_chat(
            user_id=access.user.id, kind=channel_kind, webhook_url=payload.webhook_url
        )
    except ValueError as exc:
        raise AuthFailure(
            status=422,
            code="WEBHOOK_URL_INVALID",
            title="Webhook URL invalid",
            detail="Use a valid incoming webhook URL for this channel provider.",
        ) from exc
    except WebhookAlreadyLinked as exc:
        raise AuthFailure(
            status=409,
            code="CHANNEL_ALREADY_LINKED",
            title="Channel already linked",
            detail="This incoming webhook is already connected to another account.",
        ) from exc
    except TelegramUnavailable as exc:
        raise AuthFailure(
            status=503,
            code="CHANNEL_ENCRYPTION_UNAVAILABLE",
            title="Channel unavailable",
            detail="External notification channels are not configured.",
        ) from exc
    return ChannelView.from_channel(channel)


@router.get("/me/channels", response_model=ChannelList)
async def list_channels(request: Request) -> ChannelList:
    access = await _authenticated(request)
    channels = await _repository(request).list_channels(user_id=access.user.id)
    return ChannelList(items=[ChannelView.from_channel(channel) for channel in channels])


@router.patch("/me/channels/{channel_id}", response_model=ChannelView)
async def update_channel(
    channel_id: uuid.UUID, payload: ChannelPatch, request: Request
) -> ChannelView:
    access = await _authenticated(request, require_csrf=True)
    channel = await _repository(request).set_show_amounts(
        user_id=access.user.id, channel_id=channel_id, show_amounts=payload.show_amounts
    )
    if channel is None:
        raise _channel_not_found()
    return ChannelView.from_channel(channel)


@router.delete("/me/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: uuid.UUID, request: Request) -> None:
    access = await _authenticated(request, require_csrf=True)
    if not await _repository(request).unlink(user_id=access.user.id, channel_id=channel_id):
        raise _channel_not_found()


def _reply(chat_id: int, text: str) -> dict[str, object]:
    # Answering inside the webhook response needs no outbound call or bot token here.
    return {"method": "sendMessage", "chat_id": chat_id, "text": text}


def _start_code(text: object) -> str | None:
    if not isinstance(text, str):
        return None
    command, _, argument = text.strip().partition(" ")
    # "/start@MyBot code" is how Telegram addresses a bot in a group-style command.
    if command.partition("@")[0] != "/start":
        return None
    code = argument.strip()
    return code if 0 < len(code) <= 64 else None


@router.post("/integrations/telegram/webhook", include_in_schema=False)
async def telegram_webhook(request: Request) -> dict[str, object]:
    expected = request.app.state.settings.telegram_webhook_secret
    if expected is None:
        raise _unavailable()
    supplied = request.headers.get(WEBHOOK_SECRET_HEADER, "")
    if not hmac.compare_digest(supplied.encode(), expected.get_secret_value().encode()):
        raise AuthFailure(
            status=401,
            code="WEBHOOK_UNAUTHORIZED",
            title="Unauthorized",
            detail="The webhook secret is missing or invalid.",
        )
    try:
        update_body = await request.json()
    except ValueError:
        return {"ok": True}
    message = update_body.get("message") if isinstance(update_body, dict) else None
    if not isinstance(message, dict):
        return {"ok": True}
    chat = message.get("chat")
    # Linking is only accepted in a private chat: a group id must never become a target.
    if not isinstance(chat, dict) or chat.get("type") != "private":
        return {"ok": True}
    chat_id = chat.get("id")
    code = _start_code(message.get("text"))
    if not isinstance(chat_id, int) or isinstance(chat_id, bool) or code is None:
        # Anything else is ignored: Telegram cannot trigger any other behaviour.
        return {"ok": True}
    try:
        outcome = await _repository(request).complete_link(code=code, chat_id=chat_id)
    except TelegramUnavailable:
        return {"ok": True}
    logger.info("telegram_link_attempt", extra={"outcome": outcome})
    replies = {
        LinkOutcome.LINKED: LINKED_REPLY,
        LinkOutcome.CHAT_TAKEN: CHAT_TAKEN_REPLY,
    }
    return _reply(chat_id, replies.get(outcome, INVALID_CODE_REPLY))
