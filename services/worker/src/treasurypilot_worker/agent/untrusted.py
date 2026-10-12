"""Untrusted-content wrapping (BR-070, FR-803; spec §8.1 layer 1).

External text reaches a model only through `wrap_untrusted`, as a labelled
`<untrusted source="…">` block that the fixed system policy declares to be data.
"""

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

from treasurypilot_worker.agent.secret_scan import SecretScanner, default_scanner

MAX_UNTRUSTED_CHARS = 20_000
# Raw text is cut to this multiple of the cap before sanitising, to bound the work done.
RAW_CHARS_FACTOR = 4

_REF = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_KEEP_CONTROLS = frozenset("\n\t")

_ACTIVE_OPENER = re.compile(r"<(script|style)\b[^<>]*>|<!--", re.IGNORECASE)
_ACTIVE_CLOSERS = {
    "script": re.compile(r"</script\s*>", re.IGNORECASE),
    "style": re.compile(r"</style\s*>", re.IGNORECASE),
    "<!--": re.compile(r"-->"),
}
_WRAPPER_TAG = re.compile(r"<\s*/?\s*untrusted\b[^>]*>?", re.IGNORECASE)
# Classes exclude their own opener, so a failed match stops at the next one (linear time).
_MARKDOWN_IMAGE = re.compile(r"!\[[^\[\]]*\]\([^()]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\[\]]*)\]\([^()]*\)")
_URL = re.compile(
    r"\b(?:https?|ftp)://\S+|\bwww\.\S+|\b(?:javascript|vbscript):\S+"
    r"|\bdata:[a-z]+/[a-z0-9.+-]+[;,]\S*",
    re.IGNORECASE,
)
# Attributes must be `name=value`, so "a<b and c>d" is text, not a tag.
_HTML_TAG = re.compile(
    r"</?[A-Za-z][A-Za-z0-9-]*"
    r"""(?:\s+[A-Za-z_:][\w:.-]*\s*=\s*(?:"[^"<>]*"|'[^'<>]*'|[^\s"'<>=`]+))*\s*/?>"""
)


class SourceKind(StrEnum):
    INVOICE = "invoice"
    DOCUMENT = "document"
    VENDOR = "vendor"
    TERMS = "terms"
    EMAIL = "email"


@dataclass(frozen=True)
class UntrustedSource:
    kind: SourceKind
    ref: str

    def __post_init__(self) -> None:
        if not _REF.fullmatch(self.ref):
            raise ValueError(f"untrusted source ref must match {_REF.pattern}")

    def __str__(self) -> str:
        return f"{self.kind.value}:{self.ref}"


@dataclass(frozen=True)
class UntrustedBlock:
    """Sanitised external text. Create it only with `wrap_untrusted`."""

    source: UntrustedSource
    text: str
    truncated: bool

    def render(self) -> str:
        truncated = ' truncated="true"' if self.truncated else ""
        return f'<untrusted source="{self.source}"{truncated}>\n{self.text}\n</untrusted>'


def wrap_untrusted(
    source: UntrustedSource,
    text: str,
    *,
    max_chars: int = MAX_UNTRUSTED_CHARS,
    scanner: SecretScanner | None = None,
) -> UntrustedBlock:
    """Sanitise, cap and secret-scan `text`; raises `AiInputRejected` on a secret."""

    raw_cap = max_chars * RAW_CHARS_FACTOR
    clean = sanitize(text[:raw_cap])
    truncated = len(text) > raw_cap or len(clean) > max_chars
    clean = clean[:max_chars]
    (scanner or default_scanner()).check(clean, source=str(source))
    return UntrustedBlock(source, clean, truncated)


def sanitize(text: str) -> str:
    """Strip active content and invisible characters, and neutralise wrapper tags.

    Addresses, emails and plain text are kept as they are, without Unicode normalisation,
    so quotes of suspicious instructions stay exact.
    """

    text = "".join(ch for ch in text if _visible(ch))
    text = _remove_active_blocks(text)
    text = _neutralise_wrapper_tags(text)
    text = _MARKDOWN_IMAGE.sub("", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub("[link removed]", text)
    text = _HTML_TAG.sub("", text)
    # Removing comments or tags can join fragments into a new wrapper tag.
    return _neutralise_wrapper_tags(text)


def _visible(ch: str) -> bool:
    # Cc: control characters. Cf: zero-width, bidi overrides and Unicode tag characters.
    return ch in _KEEP_CONTROLS or unicodedata.category(ch) not in ("Cc", "Cf")


def _remove_active_blocks(text: str) -> str:
    """Remove `<script>`/`<style>` blocks and comments; an unclosed opener alone is removed,
    so a stray `<!--` in OCR text does not drop the rest of the document."""

    parts: list[str] = []
    pos = 0
    unclosed: set[str] = set()  # a closer missing after one opener is missing after later ones
    while opener := _ACTIVE_OPENER.search(text, pos):
        parts.append(text[pos : opener.start()])
        kind = (opener.group(1) or "<!--").lower()
        closer = None if kind in unclosed else _ACTIVE_CLOSERS[kind].search(text, opener.end())
        if closer is None:
            unclosed.add(kind)
            pos = opener.end()
        else:
            pos = closer.end()
    parts.append(text[pos:])
    return "".join(parts)


def _neutralise_wrapper_tags(text: str) -> str:
    return _WRAPPER_TAG.sub("[tag removed]", text)
