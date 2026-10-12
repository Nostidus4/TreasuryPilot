"""Fail-closed structlog processors for sensitive values."""

from __future__ import annotations

import re
import sys
import traceback
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

REDACTED = "[REDACTED]"
_REDACTION_FAILED = "[REDACTION_FAILED]"
_CYCLE = "[REDACTED_CYCLE]"
_MAX_DEPTH = 32

_EMAIL = re.compile(r"(?<![\w.+-])[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_JWT = re.compile(r"(?<![\w-])eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_API_TOKEN = re.compile(
    r"(?<![\w-])(?:"
    r"sk-(?:ant-api\d{2}-)?[A-Za-z0-9_-]{16,}|"
    r"github_pat_[A-Za-z0-9_]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}"
    r")(?![\w-])"
)
_SIGNATURE = re.compile(r"(?i)0x[a-f0-9]{130,}")
# A bare 32-byte hex value may be a private key.  Prefixed 0x + 64 hex is not
# matched globally because it is also the canonical representation of tx hashes.
_BARE_PRIVATE_KEY = re.compile(r"(?<![0-9A-Fa-fx])[0-9A-Fa-f]{64}(?![0-9A-Fa-f])")
# Matches "key=value" / "key: value" assignments for common secret-shaped key
# names.  A `\w*` prefix/suffix lets this catch real-world variants such as
# `access_token=`, `client_secret=`, `db_password=` (not just the bare
# keyword), and an optional quote before the separator lets it catch quoted
# JSON keys such as `"password": "hunter2"`.
_ASSIGNMENT_SECRET = re.compile(
    r"(?i)\b(\w*(?:api[_-]?key|password|secret|token)\w*)"
    r"[\"']?\s*[=:]\s*[\"']?[^\s,;\"'}]+[\"']?"
)
# Substrings (not exact-suffix matches) so plurals and compound names such as
# `tokens`, `api_keys`, `passwords`, `private_key_hex`, `session_id` are all
# caught, not just the exact singular form.
_SENSITIVE_KEY_SUBSTRINGS = (
    "apikey",
    "authorization",
    "bearer",
    "cookie",
    "credential",
    "mnemonic",
    "password",
    "privatekey",
    "secret",
    "seedphrase",
    "session",
    "signature",
    "token",
)
# Fields that are domain-public asset/token addresses rather than secrets.
# Checked against the fully normalized key (lowercased, non-alnum stripped)
# so `payment_token`, `PaymentToken`, etc. all match.  Narrower than the
# generic "token" substring rule above so that `access_token`/`api_token`
# style credential fields remain redacted.
_PUBLIC_TOKEN_KEY_ALLOWLIST = frozenset(
    {
        "token",
        "paymenttoken",
        "feetoken",
        "tokenaddress",
    }
)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if normalized in _PUBLIC_TOKEN_KEY_ALLOWLIST:
        return False
    if any(substring in normalized for substring in _SENSITIVE_KEY_SUBSTRINGS):
        return True
    if normalized in {"document", "note", "notes"}:
        return True
    return ("document" in normalized or "invoice" in normalized) and any(
        content_word in normalized for content_word in ("body", "content", "text")
    )


def _redact_string(value: str) -> str:
    value = _EMAIL.sub(REDACTED, value)
    value = _BEARER.sub(REDACTED, value)
    value = _JWT.sub(REDACTED, value)
    value = _API_TOKEN.sub(REDACTED, value)
    value = _SIGNATURE.sub(REDACTED, value)
    value = _BARE_PRIVATE_KEY.sub(REDACTED, value)
    return _ASSIGNMENT_SECRET.sub(lambda match: f"{match.group(1)}={REDACTED}", value)


def _unique_key(candidate: str, taken: Mapping[str, Any]) -> str:
    if candidate not in taken:
        return candidate
    suffix = 2
    while f"{candidate}#{suffix}" in taken:
        suffix += 1
    return f"{candidate}#{suffix}"


def _redact_value(value: Any, *, key: str | None, seen: set[int], depth: int) -> Any:
    if key is not None and _is_sensitive_key(key):
        return REDACTED
    if depth > _MAX_DEPTH:
        return REDACTED
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, bytes):
        return REDACTED
    if isinstance(value, BaseException):
        return f"[{type(value).__name__}: REDACTED]"

    if isinstance(value, Mapping | list | tuple | set | frozenset):
        identity = id(value)
        if identity in seen:
            return _CYCLE
        seen.add(identity)
        try:
            if isinstance(value, Mapping):
                sanitized_mapping: dict[str, Any] = {}
                for item_key, item_value in value.items():
                    raw_key = (
                        item_key if isinstance(item_key, str) else f"[{type(item_key).__name__}]"
                    )
                    safe_key = _unique_key(_redact_string(raw_key), sanitized_mapping)
                    sanitized_mapping[safe_key] = _redact_value(
                        item_value,
                        key=raw_key,
                        seen=seen,
                        depth=depth + 1,
                    )
                return sanitized_mapping
            sanitized = [
                _redact_value(item, key=None, seen=seen, depth=depth + 1) for item in value
            ]
            if isinstance(value, tuple):
                return tuple(sanitized)
            if isinstance(value, set | frozenset):
                return sorted(sanitized, key=repr)
            return sanitized
        finally:
            seen.discard(identity)

    # Known-safe, non-secret value types: stringify and still run the result
    # through `_redact_string` (a secret-looking Decimal/str would still be
    # caught) so audit-relevant data such as amounts, ids, and timestamps
    # survives instead of collapsing to an opaque "[TypeName]" placeholder.
    if isinstance(value, Decimal | UUID | date | Enum):
        return _redact_string(str(value))

    # Do not call user-defined __str__/__repr__ for anything else; either can
    # contain secrets or throw while a log record is being processed.
    return f"[{type(value).__name__}]"


def _render_exc_info(exc_info: Any) -> str | None:
    """Render exc_info the same way structlog's format_exc_info would.

    structlog treats any truthy, non-tuple `exc_info` as "render the current
    exception" and calls `sys.exc_info()` itself later in the processor
    chain -- after redaction has already run.  That means a plain
    `logger.exception(...)` (which sets `exc_info=True`) or any other
    truthy `exc_info` value renders the full, unredacted traceback
    downstream.  Rendering here, before the traceback string is redacted,
    closes that gap.
    """

    if not exc_info:
        return None
    if isinstance(exc_info, tuple):
        exc_type, exc_value, exc_tb = exc_info
    elif isinstance(exc_info, BaseException):
        exc_type, exc_value, exc_tb = type(exc_info), exc_info, exc_info.__traceback__
    else:
        exc_type, exc_value, exc_tb = sys.exc_info()
    if exc_type is None:
        return None
    try:
        return "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    except Exception:  # pragma: no cover - defense against hostile traceback state
        return None


def _render_stack_info(stack_info: Any) -> str | None:
    if not stack_info:
        return None
    try:
        return "".join(traceback.format_stack())
    except Exception:  # pragma: no cover - defense against hostile frame state
        return None


def redact_event(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy of a structlog event dictionary.

    If unexpected input defeats sanitization, the original event is discarded
    so logging cannot become a side channel for sensitive data.
    """

    try:
        working = dict(event_dict)
        exc_info = working.pop("exc_info", None)
        stack_info = working.pop("stack_info", None)
        rendered_exc = _render_exc_info(exc_info)
        rendered_stack = _render_stack_info(stack_info)

        sanitized = _redact_value(working, key=None, seen=set(), depth=0)
        if not isinstance(sanitized, dict):
            raise TypeError
        if rendered_exc is not None:
            sanitized["exception"] = _redact_string(rendered_exc)
        if rendered_stack is not None:
            sanitized["stack"] = _redact_string(rendered_stack)
        return sanitized
    except Exception:  # pragma: no cover - defense against hostile logging values
        return {"event": _REDACTION_FAILED}
