"""Signed, retryable outbound webhook delivery from the domain-event outbox."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import random
import socket
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

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
_LEASE = """
UPDATE webhook_deliveries SET next_attempt_at = now() + make_interval(secs => $2)
WHERE id = ANY($1::uuid[])
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


class _BlockedDestination(ValueError):
    """The webhook URL targets a non-public IP literal."""


def _reject_non_public_literal(url: str) -> None:
    """The resolver never runs for IP-literal hosts, so check those before connecting."""

    try:
        address = ipaddress.ip_address((urlsplit(url).hostname or "").strip("[]"))
    except ValueError:
        return  # a DNS name: _PublicResolver checks what it resolves to
    if not address.is_global:
        raise _BlockedDestination("webhook URL targets a non-public IP address")


def is_permanent_status(status_code: int) -> bool:
    """4xx means the receiver rejected the event; only 408/429 are worth retrying."""

    return 400 <= status_code < 500 and status_code not in (408, 429)


def retry_delay_seconds(attempts: int) -> float:
    """Backoff for the next send, jittered +-20% so failing endpoints do not sync up."""

    delay = _BACKOFF_SECONDS[min(attempts - 1, len(_BACKOFF_SECONDS) - 1)]
    return delay * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not security


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


async def _send(
    client: aiohttp.ClientSession, cipher: FieldCipher, row: asyncpg.Record
) -> tuple[int | None, str | None, bool]:
    """POST one signed event; returns (status code, error or None on success, permanent)."""

    try:
        _reject_non_public_literal(row["url"])
        secret = cipher.decrypt(
            bytes(row["secret_ciphertext"]).decode(),
            context=f"webhook_endpoints:{row['endpoint_id']}:secret".encode(),
        )
        body = event_envelope(row)
        async with client.post(
            row["url"],
            data=body,
            headers=signature_headers(
                secret=secret, event_id=row["event_id"], body=body, timestamp=int(time.time())
            ),
            allow_redirects=False,
        ) as response:
            status_code = response.status
        if 200 <= status_code < 300:
            return status_code, None, False
        # Keep endpoint response content out of logs and persistent state.
        return status_code, f"HTTP {status_code}", is_permanent_status(status_code)
    except _BlockedDestination:
        return None, "BlockedDestination", True
    except Exception as exc:  # noqa: BLE001 - one bad row must not strand the rest of the batch
        return None, type(exc).__name__, False


async def deliver_pending_webhooks(
    connection: asyncpg.Connection,
    *,
    encryption_key: FieldEncryptionKey,
    batch_size: int = 50,
    request_timeout_seconds: float = 5.0,
) -> int:
    """Lease a batch, send it outside any transaction, then record each outcome.

    The lease pushes ``next_attempt_at`` past the worst-case batch duration, so a crash
    mid-send only delays (and may repeat) deliveries; it never holds row locks over I/O.
    """

    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    cipher = FieldCipher(encryption_key)
    lease_seconds = batch_size * request_timeout_seconds + 30
    async with connection.transaction():
        rows = await connection.fetch(_CLAIM, batch_size)
        if rows:
            await connection.execute(_LEASE, [row["id"] for row in rows], lease_seconds)
    delivered = 0
    timeout = aiohttp.ClientTimeout(total=request_timeout_seconds)
    connector = aiohttp.TCPConnector(resolver=_PublicResolver(), use_dns_cache=False)
    async with aiohttp.ClientSession(
        timeout=timeout, raise_for_status=False, connector=connector
    ) as client:
        for row in rows:
            attempts = row["attempt_count"] + 1
            status_code, error, permanent = await _send(client, cipher, row)
            if error is None:
                await connection.execute(_DELIVERED, row["id"], attempts, status_code)
                delivered += 1
            elif permanent or attempts >= MAX_ATTEMPTS:
                await connection.execute(
                    _FAILED, row["id"], "dead", attempts, datetime.now(UTC), status_code, error
                )
            else:
                await connection.execute(
                    _FAILED,
                    row["id"],
                    "retrying",
                    attempts,
                    datetime.now(UTC) + timedelta(seconds=retry_delay_seconds(attempts)),
                    status_code,
                    error,
                )
    return delivered
