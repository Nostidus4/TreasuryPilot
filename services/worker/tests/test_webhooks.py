from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import time
import uuid
from typing import Any

import pytest

from treasurypilot_core.privacy import FieldEncryptionKey
from treasurypilot_worker.notify import webhooks
from treasurypilot_worker.notify.webhooks import signature_headers, verify_signature


def test_signature_uses_documented_hmac_sha256_format(monkeypatch: Any) -> None:
    monkeypatch.setattr(time, "time", lambda: 1_800_000_000)
    body = b'{"id":"evt-1"}'
    key = b"secret-key"
    event_id = uuid.UUID("018f47e3-1b6a-7cc0-8b36-f6c991f64e52")

    headers = signature_headers(secret=key, event_id=event_id, body=body, timestamp=1_800_000_000)
    digest = hmac.new(key, b"1800000000." + body, hashlib.sha256).hexdigest()

    assert headers["X-TP-Signature"] == f"t=1800000000,v1={digest}"
    assert headers["X-TP-Event-Id"] == str(event_id)
    assert verify_signature(secret=key, body=body, header=headers["X-TP-Signature"])
    assert not verify_signature(secret=key, body=body + b"!", header=headers["X-TP-Signature"])
    assert not verify_signature(secret=key, body=body, header="malformed")


def test_signature_verifier_rejects_stale_timestamp(monkeypatch: Any) -> None:
    monkeypatch.setattr(time, "time", lambda: 1_800_000_000)
    body = b"{}"
    header = signature_headers(secret=b"secret", event_id=uuid.uuid4(), body=body, timestamp=1)

    assert not verify_signature(secret=b"secret", body=body, header=header["X-TP-Signature"])


class _Tx:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    async def __aenter__(self) -> None:
        self.connection.in_transaction = True

    async def __aexit__(self, *_: object) -> None:
        self.connection.in_transaction = False


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.in_transaction = False
        self.updates: list[tuple[Any, ...]] = []
        self.leased: list[Any] = []

    def transaction(self) -> _Tx:
        return _Tx(self)

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        assert self.in_transaction
        return self.rows

    async def execute(self, query: str, *args: Any) -> str:
        if "next_attempt_at = now() +" in query:
            assert self.in_transaction
            self.leased.append(args[0])
        else:
            assert not self.in_transaction  # outcomes are written per row, outside the claim
            self.updates.append(args)
        return "UPDATE 1"


def _row(url: str = "https://hooks.example.test/e", attempts: int = 0) -> dict[str, Any]:
    return {"id": uuid.uuid4(), "url": url, "attempt_count": attempts}


def _deliver(connection: _FakeConnection) -> int:
    return asyncio.run(
        webhooks.deliver_pending_webhooks(
            connection,  # type: ignore[arg-type]
            encryption_key=FieldEncryptionKey.from_base64(
                base64.urlsafe_b64encode(b"k" * 32).decode()
            ),
        )
    )


def test_batch_is_leased_then_sent_outside_the_claim_transaction(monkeypatch: Any) -> None:
    rows = [_row(), _row()]
    connection = _FakeConnection(rows)

    async def send(*_: Any) -> tuple[int | None, str | None, bool]:
        assert not connection.in_transaction  # no locks held across HTTP I/O
        return 204, None, False

    monkeypatch.setattr(webhooks, "_send", send)

    assert _deliver(connection) == 2
    assert connection.leased == [[row["id"] for row in rows]]
    assert [update[0] for update in connection.updates] == [row["id"] for row in rows]


def test_one_failing_row_does_not_strand_the_others(monkeypatch: Any) -> None:
    connection = _FakeConnection([_row(), _row()])
    outcomes = iter([(None, "RuntimeError", False), (204, None, False)])

    async def send(*_: Any) -> tuple[int | None, str | None, bool]:
        return next(outcomes)

    monkeypatch.setattr(webhooks, "_send", send)

    assert _deliver(connection) == 1
    assert connection.updates[0][1] == "retrying"
    assert connection.updates[0][5] == "RuntimeError"


def test_send_records_any_exception_instead_of_raising(monkeypatch: Any) -> None:
    class Cipher:
        def decrypt(self, *_: Any, **__: Any) -> bytes:
            return b"secret"

    class Client:
        def post(self, *_: Any, **__: Any) -> Any:
            raise RuntimeError("boom")

    monkeypatch.setattr(webhooks, "event_envelope", lambda row: b"{}")
    row = _row() | {
        "secret_ciphertext": b"x",
        "endpoint_id": uuid.uuid4(),
        "event_id": uuid.uuid4(),
    }

    result = asyncio.run(webhooks._send(Client(), Cipher(), row))  # type: ignore[arg-type]

    assert result == (None, "RuntimeError", False)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/e",
        "https://10.0.0.5/e",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/e",
        "https://[::ffff:127.0.0.1]/e",
    ],
)
def test_non_public_ip_literals_are_blocked_before_any_request(url: str) -> None:
    class Client:
        def post(self, *_: Any, **__: Any) -> Any:
            raise AssertionError("must not connect")

    result = asyncio.run(webhooks._send(Client(), None, _row(url)))  # type: ignore[arg-type]

    assert result == (None, "BlockedDestination", True)


@pytest.mark.parametrize(
    ("status", "permanent"),
    [
        (400, True),
        (401, True),
        (404, True),
        (410, True),
        (408, False),
        (429, False),
        (500, False),
        (503, False),
        (302, False),
    ],
)
def test_only_non_transient_4xx_are_permanent(status: int, permanent: bool) -> None:
    assert webhooks.is_permanent_status(status) is permanent


def test_permanent_rejection_is_dead_lettered_on_the_first_attempt(monkeypatch: Any) -> None:
    connection = _FakeConnection([_row()])

    async def send(*_: Any) -> tuple[int | None, str | None, bool]:
        return 404, "HTTP 404", True

    monkeypatch.setattr(webhooks, "_send", send)

    assert _deliver(connection) == 0
    assert connection.updates[0][1] == "dead"


def test_retry_delay_is_jittered_around_the_backoff_schedule() -> None:
    delays = {webhooks.retry_delay_seconds(3) for _ in range(50)}

    assert len(delays) > 1
    assert all(24 <= delay <= 36 for delay in delays)  # 30 s +-20%
    assert 2800 <= webhooks.retry_delay_seconds(99) <= 4400  # capped at the last step
