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

_REF = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_KEEP_CONTROLS = frozenset("\n\t")

_ACTIVE_BLOCK = re.compile(
    r"<(script|style)\b[^>]*>.*?(?:</\1\s*>|$)|<!--.*?(?:-->|$)", re.IGNORECASE | re.DOTALL
)
_WRAPPER_TAG = re.compile(r"<\s*/?\s*untrusted\b[^>]*>?", re.IGNORECASE)
_MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(
    r"\b(?:https?|ftp)://\S+|\bwww\.\S+|\b(?:javascript|vbscript):\S+"
    r"|\bdata:[a-z]+/[a-z0-9.+-]+[;,]\S*",
    re.IGNORECASE,
)
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")


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

    clean = sanitize(text)
    truncated = len(clean) > max_chars
    clean = clean[:max_chars]
    (scanner or default_scanner()).check(clean, source=str(source))
    return UntrustedBlock(source, clean, truncated)


def sanitize(text: str) -> str:
    """Strip active content and invisible characters, and neutralise wrapper tags.

    Addresses, emails and plain text are kept as they are, without Unicode normalisation,
    so quotes of suspicious instructions stay exact.
    """

    text = "".join(ch for ch in text if _visible(ch))
    text = _ACTIVE_BLOCK.sub("", text)
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


def _neutralise_wrapper_tags(text: str) -> str:
    return _WRAPPER_TAG.sub("[tag removed]", text)
