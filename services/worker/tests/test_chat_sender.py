"""Chat delivery queue integration (set TEST_DATABASE_URL to a migrated database)."""

from __future__ import annotations

import asyncio
import base64
import os
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify.chat_adapters import ChatPlatform
from treasurypilot_worker.notify.chat_sender import deliver_chat_pending

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        "TEST_DATABASE_URL" not in os.environ,
        reason="TEST_DATABASE_URL is required for chat delivery integration tests",
    ),
]

CIPHER = FieldCipher(
    FieldEncryptionKey.from_base64(base64.urlsafe_b64encode(bytes(range(32))).decode())
)
BASE_URL = "https://app.example.test"
WEBHOOK_URL = "https://hooks.slack.com/services/T/B/secret"


class FakeChatClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_message(self, webhook_url: str, text_value: str) -> None:
        self.sent.append((webhook_url, text_value))


def test_action_notification_is_delivered_to_encrypted_chat_target() -> None:
    async def run() -> None:
        engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        pool = await create_worker_pool(os.environ["TEST_DATABASE_URL"], min_size=1, max_size=1)
        org_id, user_id, event_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        channel_id, notification_id = uuid.uuid4(), uuid.uuid4()
        moment = datetime.now(UTC)
        client = FakeChatClient()
        try:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("INSERT INTO organizations (id, name) VALUES (:id, 'Chat test')"),
                    {"id": org_id},
                )
                await session.execute(
                    text("INSERT INTO users (id, email) VALUES (:id, :email)"),
                    {"id": user_id, "email": f"chat-{user_id}@example.test"},
                )
                await session.execute(
                    text(
                        "INSERT INTO notification_channels "
                        "(id,user_id,kind,target,target_hash,verified_at) "
                        "VALUES (:id,:user,'SLACK',:target,:hash,:verified)"
                    ),
                    {
                        "id": channel_id,
                        "user": user_id,
                        "target": CIPHER.encrypt_text(
                            WEBHOOK_URL, context="notification_channels.target"
                        ),
                        "hash": bytes(range(32)),
                        "verified": moment,
                    },
                )
                await session.execute(
                    text(
                        "INSERT INTO domain_events "
                        "(id,org_id,type,entity_type,entity_id,payload,published_at) "
                        "VALUES (:id,:org,'ApprovalNeeded','payment_request',:entity,'{}'::jsonb,now())"
                    ),
                    {"id": event_id, "org": org_id, "entity": uuid.uuid4()},
                )
                await session.execute(
                    text(
                        "INSERT INTO notifications "
                        "(id,org_id,user_id,event_id,type,title,body,link,severity) "
                        "VALUES (:id,:org,:user,:event,'ApprovalNeeded','Approval required',"
                        "'generic body','/requests/example','ACTION')"
                    ),
                    {"id": notification_id, "org": org_id, "user": user_id, "event": event_id},
                )
            sent = await deliver_chat_pending(
                pool,
                clients={ChatPlatform.SLACK: client},
                cipher=CIPHER,
                base_url=BASE_URL,
                now=moment,
            )
            assert sent == 1
            assert client.sent == [
                (
                    WEBHOOK_URL,
                    f"[TreasuryPilot] Approval required · open: {BASE_URL}/requests/example",
                )
            ]
        finally:
            async with sessions() as session, session.begin():
                await session.execute(text("DELETE FROM users WHERE id=:id"), {"id": user_id})
                await session.execute(
                    text("DELETE FROM domain_events WHERE id=:id"), {"id": event_id}
                )
                await session.execute(
                    text("DELETE FROM organizations WHERE id=:id"), {"id": org_id}
                )
            await pool.close()
            await engine.dispose()

    asyncio.run(run())
