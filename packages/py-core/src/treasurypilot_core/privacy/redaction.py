"""Fail-closed structlog processors for sensitive values."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

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
_ASSIGNMENT_SECRET = re.compile(r"(?i)\b(api[_-]?key|password|secret|token)\s*[=:]\s*[^\s,;]+")
_SENSITIVE_KEY_SUFFIXES = (
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "privatekey",
    "secret",
    "signature",
    "signatures",
    "token",
)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if normalized.endswith(_SENSITIVE_KEY_SUFFIXES):
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
        next_seen = seen | {identity}
        if isinstance(value, Mapping):
            sanitized_mapping: dict[str, Any] = {}
            for item_key, item_value in value.items():
                raw_key = item_key if isinstance(item_key, str) else f"[{type(item_key).__name__}]"
                safe_key = _redact_string(raw_key)
                sanitized_mapping[safe_key] = _redact_value(
                    item_value,
                    key=raw_key,
                    seen=next_seen,
                    depth=depth + 1,
                )
            return sanitized_mapping
        sanitized = [
            _redact_value(item, key=None, seen=next_seen, depth=depth + 1) for item in value
        ]
        if isinstance(value, tuple):
            return tuple(sanitized)
        if isinstance(value, set | frozenset):
            return sorted(sanitized, key=repr)
        return sanitized

    # Do not call user-defined __str__/__repr__; either can contain secrets or
    # throw while a log record is being processed.
    return f"[{type(value).__name__}]"


def redact_event(_logger: Any, _method_name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy of a structlog event dictionary.

    If unexpected input defeats sanitization, the original event is discarded
    so logging cannot become a side channel for sensitive data.
    """

    try:
        sanitized = _redact_value(event_dict, key=None, seen=set(), depth=0)
        if not isinstance(sanitized, dict):
            raise TypeError
        return sanitized
    except Exception:  # pragma: no cover - defense against hostile logging values
        return {"event": _REDACTION_FAILED}
