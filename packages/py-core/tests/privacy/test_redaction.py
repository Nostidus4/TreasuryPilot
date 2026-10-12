import copy
import json

import structlog

from treasurypilot_core.privacy import REDACTED, redact_event


def test_redacts_nested_sensitive_values_without_mutating_input() -> None:
    signature = "0x" + "ab" * 65
    event = {
        "event": "invoice parsed for owner@example.com",
        "vendor": {
            "contact": "finance@example.com",
            "document_text": "Pay secret invoice details",
        },
        "headers": {"Authorization": "Bearer live-token"},
        "documentBody": "camel-case document secret",
        "signature": signature,
        "items": ["safe", {"api_key": "provider-secret"}],
    }
    original = copy.deepcopy(event)

    result = redact_event(None, "info", event)

    assert event == original
    assert result == {
        "event": f"invoice parsed for {REDACTED}",
        "vendor": {"contact": REDACTED, "document_text": REDACTED},
        "headers": {"Authorization": REDACTED},
        "documentBody": REDACTED,
        "signature": REDACTED,
        "items": ["safe", {"api_key": REDACTED}],
    }


def test_structlog_sample_contains_no_sensitive_markers() -> None:
    output: list[str] = []
    logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_ListWriter(output)),
        processors=[redact_event, structlog.processors.JSONRenderer(sort_keys=True)],
    )
    sensitive_markers = [
        "alice@example.com",
        "invoice body must not escape",
        "provider-token-value",
        "0x" + "cd" * 65,
        "a1" * 32,
        "exception-password",
        "sk-ant-api03-abcdefghijklmnopqrstuv",
    ]

    logger.error(
        f"processing {sensitive_markers[0]}",
        document_text=sensitive_markers[1],
        nested={
            "api_token": sensitive_markers[2],
            "signature": sensitive_markers[3],
            "candidate": sensitive_markers[4],
        },
        error=RuntimeError(sensitive_markers[5]),
        provider_response=f"failed token {sensitive_markers[6]}",
    )

    rendered = "\n".join(output)
    json.loads(rendered)
    assert REDACTED in rendered
    for marker in sensitive_markers:
        assert marker not in rendered


def test_preserves_addresses_and_transaction_hashes_for_audit() -> None:
    address = "0x" + "12" * 20
    transaction_hash = "0x" + "34" * 32

    result = redact_event(
        None,
        "info",
        {"address": address, "tx_hash": transaction_hash},
    )

    assert result == {"address": address, "tx_hash": transaction_hash}


def test_cycles_and_exception_objects_do_not_leak() -> None:
    cyclic: dict[str, object] = {"email": "cycle@example.com"}
    cyclic["self"] = cyclic

    result = redact_event(
        None,
        "error",
        {"payload": cyclic, "exception": ValueError("password=hunter2")},
    )

    assert result["payload"] == {"email": REDACTED, "self": "[REDACTED_CYCLE]"}
    assert result["exception"] == "[ValueError: REDACTED]"
    assert "hunter2" not in repr(result)


def test_sensitive_mapping_keys_and_camel_case_credentials_are_redacted() -> None:
    result = redact_event(
        None,
        "info",
        {
            "alice@example.com": "member",
            "credentials": {"accessToken": "opaque", "privateKey": "private"},
        },
    )

    assert result == {
        REDACTED: "member",
        "credentials": {"accessToken": REDACTED, "privateKey": REDACTED},
    }


class _ListWriter:
    def __init__(self, output: list[str]) -> None:
        self.output = output

    def write(self, message: str) -> None:
        self.output.append(message)

    def flush(self) -> None:
        pass
