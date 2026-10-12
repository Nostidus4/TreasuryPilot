import copy
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum

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

    # "credentials" itself now matches the (plural-aware) "credential"
    # substring rule, so the whole container is redacted rather than
    # recursed into -- still safe, just coarser.
    assert result == {REDACTED: "member", "credentials": REDACTED}


def test_exc_info_true_is_rendered_and_redacted() -> None:
    output: list[str] = []
    logger = structlog.wrap_logger(
        structlog.PrintLogger(file=_ListWriter(output)),
        processors=[
            redact_event,
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
    )

    try:
        raise ValueError("password=hunter2-secret")
    except ValueError:
        logger.exception("request failed", password="hunter2-secret")

    rendered = "\n".join(output)
    assert "hunter2-secret" not in rendered
    assert REDACTED in rendered
    # exc_info must not survive as a field for structlog's own exc_info
    # renderer to pick up -- that renderer would call sys.exc_info() again
    # and re-render the unredacted traceback.
    assert '"exc_info"' not in rendered


def test_exc_info_exception_instance_is_rendered_and_redacted() -> None:
    try:
        raise RuntimeError("api_key=super-secret-value")
    except RuntimeError as caught:
        result = redact_event(None, "error", {"event": "boom", "exc_info": caught})

    assert "super-secret-value" not in json.dumps(result)
    assert "exception" in result
    assert REDACTED in result["exception"]
    assert "RuntimeError" in result["exception"]


def test_stack_info_is_rendered_and_redacted() -> None:
    result = redact_event(
        None,
        "info",
        {"event": "trace", "stack_info": True, "secret": "token=abc123"},
    )

    assert "stack" in result
    assert "token=abc123" not in json.dumps(result)


def test_assignment_regex_catches_common_key_variants() -> None:
    result = redact_event(
        None,
        "info",
        {
            "message": "access_token=abc123 client_secret=xyz db_password=hunter2",
            "json_like": '{"password": "hunter2"}',
        },
    )

    rendered = json.dumps(result)
    for marker in ("abc123", "xyz", "hunter2"):
        assert marker not in rendered


def test_plural_and_compound_key_names_are_redacted() -> None:
    result = redact_event(
        None,
        "info",
        {
            "tokens": "abc",
            "api_keys": "abc",
            "secrets": "abc",
            "passwords": "abc",
            "private_key_hex": "abc",
            "cookie": "abc",
            "session": "abc",
            "seed_phrase": "wood river apple lamp",
            "mnemonic": "wood river apple lamp",
        },
    )

    for value in result.values():
        assert value == REDACTED


def test_public_token_address_fields_are_preserved() -> None:
    address = "0x" + "ab" * 20
    result = redact_event(
        None,
        "info",
        {"token": address, "payment_token": address, "fee_token": address},
    )

    assert result == {"token": address, "payment_token": address, "fee_token": address}


def test_non_primitive_safe_types_are_stringified_not_opaque() -> None:
    amount = Decimal("1234.56")
    identifier = uuid.uuid4()
    when = datetime(2026, 1, 1, tzinfo=UTC)
    today = date(2026, 1, 1)

    class Status(Enum):
        OPEN = "open"

    result = redact_event(
        None,
        "info",
        {
            "amount": amount,
            "id": identifier,
            "created_at": when,
            "due_date": today,
            "status": Status.OPEN,
        },
    )

    assert result["amount"] == str(amount)
    assert result["id"] == str(identifier)
    assert result["created_at"] == str(when)
    assert result["due_date"] == str(today)
    assert result["status"] == str(Status.OPEN)
    for value in result.values():
        assert not value.startswith("[") or value == REDACTED


def test_non_primitive_value_that_looks_like_a_secret_still_redacted() -> None:
    class FakeSecret(StrEnum):
        LEAK = "password=hunter2"

    result = redact_event(None, "info", {"note_field": FakeSecret.LEAK})

    assert "hunter2" not in json.dumps(result)


def test_redacted_string_keys_do_not_collide() -> None:
    result = redact_event(
        None,
        "info",
        {"alice@example.com": "owner", "bob@example.com": "viewer"},
    )

    assert len(result) == 2
    assert set(result.values()) == {"owner", "viewer"}
    assert all(key == REDACTED or key.startswith(f"{REDACTED}#") for key in result)


def test_non_str_keys_do_not_collide() -> None:
    result = redact_event(None, "info", {1: "a", 2: "b"})

    assert len(result) == 2
    assert set(result.values()) == {"a", "b"}


class _ListWriter:
    def __init__(self, output: list[str]) -> None:
        self.output = output

    def write(self, message: str) -> None:
        self.output.append(message)

    def flush(self) -> None:
        pass
