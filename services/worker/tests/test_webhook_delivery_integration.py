from __future__ import annotations

import asyncio
import base64
import json
import os
import uuid
from typing import Any

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey
from treasurypilot_worker.locks import create_worker_pool
from treasurypilot_worker.notify import webhooks as webhook_module
from treasurypilot_worker.notify.publisher import publish_from_pool
from treasurypilot_worker.notify.webhooks import deliver_pending_webhooks, verify_signature


@pytest.mark.integration
@pytest.mark.skipif(
    "TEST_DATABASE_URL" not in os.environ,
    reason="TEST_DATABASE_URL is required for PostgreSQL webhook delivery integration",
)
def test_domain_event_is_signed_delivered_and_persisted(monkeypatch: Any) -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    organization_id = uuid.uuid4()
    endpoint_id = uuid.uuid4()
    event_id = uuid.uuid4()
    entity_id = uuid.uuid4()
    secret = b"integration-webhook-secret"
    key = FieldEncryptionKey.from_base64(base64.urlsafe_b64encode(os.urandom(32)).decode())
    encrypted = FieldCipher(key).encrypt(
        secret, context=f"webhook_endpoints:{endpoint_id}:secret".encode()
    )
    received: list[tuple[bytes, str | None]] = []

    async def exercise() -> None:
        async def receive(request: web.Request) -> web.Response:
            received.append((await request.read(), request.headers.get("X-TP-Signature")))
            return web.Response(status=204)

        application = web.Application()
        application.router.add_post("/events", receive)
        server = TestServer(application)
        await server.start_server()
        # This test uses a local loopback receiver; production keeps the resolver
        # that permits only public destinations.
        monkeypatch.setattr(webhook_module, "_PublicResolver", aiohttp.resolver.DefaultResolver)
        monkeypatch.setattr(webhook_module, "_reject_non_public_literal", lambda url: None)
        # The table only stores https URLs and the receiver is plain HTTP: downgrade on read.
        monkeypatch.setattr(
            webhook_module,
            "_CLAIM",
            webhook_module._CLAIM.replace(
                "e.url,", "replace(e.url, 'https://', 'http://') AS url,"
            ),
        )
        pool = await create_worker_pool(database_url, min_size=1, max_size=1)
        try:
            async with pool.acquire() as connection, connection.transaction():
                await connection.execute(
                    "INSERT INTO organizations (id, name) VALUES ($1, $2)",
                    organization_id,
                    "Webhook delivery integration",
                )
                await connection.execute(
                    "INSERT INTO webhook_endpoints "
                    "(id, org_id, url, secret_ciphertext, event_types) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    endpoint_id,
                    organization_id,
                    f"{server.make_url('/events')}".replace("http://", "https://"),
                    encrypted.encode(),
                    ["ApprovalNeeded"],
                )
                await connection.execute(
                    "INSERT INTO domain_events (id, org_id, type, entity_type, entity_id, payload) "
                    "VALUES ($1, $2, 'ApprovalNeeded', 'payment_request', $3, $4::jsonb)",
                    event_id,
                    organization_id,
                    entity_id,
                    json.dumps({"requestId": str(entity_id)}),
                )

            assert await publish_from_pool(pool) == 1
            async with pool.acquire() as connection:
                assert await deliver_pending_webhooks(connection, encryption_key=key) == 1
                delivery_status = await connection.fetchval(
                    "SELECT status FROM webhook_deliveries WHERE event_id=$1 AND endpoint_id=$2",
                    event_id,
                    endpoint_id,
                )
            assert delivery_status == "delivered"
            assert len(received) == 1
            body, signature = received[0]
            assert signature is not None
            assert verify_signature(secret=secret, body=body, header=signature)
            assert json.loads(body)["id"] == str(event_id)
        finally:
            async with pool.acquire() as connection:
                await connection.execute("DELETE FROM domain_events WHERE id=$1", event_id)
                await connection.execute("DELETE FROM webhook_endpoints WHERE id=$1", endpoint_id)
                await connection.execute("DELETE FROM organizations WHERE id=$1", organization_id)
            await pool.close()
            await server.close()

    asyncio.run(exercise())
