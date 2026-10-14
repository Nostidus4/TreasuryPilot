"""Signed, retryable outbound webhook delivery from the domain-event outbox."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import aiohttp
import asyncpg  # type: ignore[import-untyped]

from treasurypilot_core.privacy import FieldCipher, FieldEncryptionKey

MAX_ATTEMPTS = 8
_BACKOFF_SECONDS = (1, 5, 30, 120, 600, 1800, 3600)
_CLAIM = """
SELECT d.id, d.org_id, d.endpoint_id, d.event_id, d.attempt_count,
       e.url, e.secret_ciphertext, ev.type AS event_type, ev.entity_type,
       ev.entity_id, ev.treasury_id, ev.payload, ev.created_at
FROM webhook_deliveries d
JOIN webhook_endpoints e ON e.id = d.endpoint_id AND e.org_id = d.org_id
JOIN domain_events ev ON ev.id = d.event_id AND ev.org_id = d.org_id
WHERE d.status IN ('pending', 'retrying') AND d.next_attempt_at <= now()
  AND e.enabled
ORDER BY d.next_attempt_at, d.id
LIMIT $1 FOR UPDATE OF d SKIP LOCKED
"""
_DELIVERED = """
UPDATE webhook_deliveries SET status='delivered', delivered_at=now(),
    attempt_count=$2, last_status_code=$3, last_error=NULL
WHERE id=$1
"""
_FAILED = """
UPDATE webhook_deliveries SET status=$2, attempt_count=$3,
    next_attempt_at=$4, last_status_code=$5, last_error=$6
WHERE id=$1
"""


class _PublicResolver(aiohttp.abc.AbstractResolver):
    """Resolve webhook hosts to public IPs only, preventing private-network SSRF."""

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_UNSPEC
    ) -> list[aiohttp.abc.ResolveResult]:
        loop = asyncio.get_running_loop()
        results = await loop.getaddrinfo(host, port, family=family, type=socket.SOCK_STREAM)
        addresses: list[aiohttp.abc.ResolveResult] = []
        for address_family, _, proto, _, sockaddr in results:
            ip = ipaddress.ip_address(sockaddr[0])
            if not ip.is_global:
                raise OSError("webhook host resolved to a non-public address")
            addresses.append(
                {
                    "hostname": host,
                    "host": ip.compressed,
                    "port": port,
                    "family": address_family,
                    "proto": proto,
                    "flags": 0,
                }
            )
        if not addresses:
            raise OSError("webhook host has no public address")
        return addresses

    async def close(self) -> None:
        return None


def event_envelope(event: asyncpg.Record) -> bytes:
    """Serialize the ids-only event envelope in stable UTF-8 JSON bytes."""

    payload: Any = event["payload"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError("domain event payload must be a JSON object")
    envelope = {
        "id": str(event["event_id"]),
        "organizationId": str(event["org_id"]),
        "type": event["event_type"],
        "createdAt": event["created_at"].astimezone(UTC).isoformat(),
        "treasuryId": str(event["treasury_id"]) if event["treasury_id"] else None,
        "entity": {"type": event["entity_type"], "id": str(event["entity_id"])},
        "payload": payload,
    }
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode()


def signature_headers(
    *, secret: bytes, event_id: uuid.UUID, body: bytes, timestamp: int
) -> dict[str, str]:
    """Sign ``timestamp.body`` with HMAC-SHA256; receivers compare v1 in constant time."""

    digest = hmac.new(secret, str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "TreasuryPilot-Webhooks/1.0",
        "X-TP-Event-Id": str(event_id),
        "X-TP-Signature": f"t={timestamp},v1={digest}",
    }


def verify_signature(
    *, secret: bytes, body: bytes, header: str, tolerance_seconds: int = 300
) -> bool:
    """Reference verifier for integrations; rejects stale signatures and malformed headers."""

    try:
        fields = dict(piece.split("=", 1) for piece in header.split(","))
        timestamp = int(fields["t"])
        supplied = fields["v1"]
    except (ValueError, KeyError):
        return False
    if abs(int(time.time()) - timestamp) > tolerance_seconds:
        return False
    expected = hmac.new(secret, str(timestamp).encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)


async def deliver_pending_webhooks(
    connection: asyncpg.Connection,
    *,
    encryption_key: FieldEncryptionKey,
    batch_size: int = 50,
    request_timeout_seconds: float = 5.0,
) -> int:
    """Claim and send a batch atomically with bounded retry and dead-letter state."""

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    cipher = FieldCipher(encryption_key)
    delivered = 0
    async with connection.transaction():
        rows = await connection.fetch(_CLAIM, batch_size)
        timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)
        connector = aiohttp.TCPConnector(resolver=_PublicResolver(), use_dns_cache=False)
        async with aiohttp.ClientSession(
            timeout=timeout, raise_for_status=False, connector=connector
        ) as client:
            for row in rows:
                attempts = row["attempt_count"] + 1
                try:
                    secret = cipher.decrypt(
                        bytes(row["secret_ciphertext"]).decode(),
                        context=f"webhook_endpoints:{row['endpoint_id']}:secret".encode(),
                    )
                    body = event_envelope(row)
                    timestamp = int(time.time())
                    async with client.post(
                        row["url"],
                        data=body,
                        headers=signature_headers(
                            secret=secret,
                            event_id=row["event_id"],
                            body=body,
                            timestamp=timestamp,
                        ),
                        allow_redirects=False,
                    ) as response:
                        status_code = response.status
                        success = 200 <= status_code < 300
                        # Keep endpoint response content out of logs and persistent state.
                        error = None if success else f"HTTP {status_code}"
                except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                    status_code = None
                    success = False
                    error = type(exc).__name__

                if success:
                    await connection.execute(_DELIVERED, row["id"], attempts, status_code)
                    delivered += 1
                    continue
                if attempts >= MAX_ATTEMPTS:
                    await connection.execute(
                        _FAILED, row["id"], "dead", attempts, datetime.now(UTC), status_code, error
                    )
                else:
                    delay = _BACKOFF_SECONDS[min(attempts - 1, len(_BACKOFF_SECONDS) - 1)]
                    await connection.execute(
                        _FAILED,
                        row["id"],
                        "retrying",
                        attempts,
                        datetime.now(UTC) + timedelta(seconds=delay),
                        status_code,
                        error,
                    )
    return delivered
