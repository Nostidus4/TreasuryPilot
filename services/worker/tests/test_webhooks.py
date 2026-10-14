from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from typing import Any

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
