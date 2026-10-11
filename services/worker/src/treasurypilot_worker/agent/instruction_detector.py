"""Deterministic instruction-text fallback (FR-312, BR-070; spec §8.1 layer 4).

Used when the LLM is unavailable, so a scan always reports reduced coverage. Detection
is advisory only: it never changes a field, a payee or a state (F-036).

A strong signal is flagged on its own. Weak signals are flagged only when at least two
different kinds sit close together on one page, because each alone is ordinary invoice
text ("Pay to: Acme Ltd", "instead of Monday"). An address unknown to the payee registry
is a weak signal; on its own it is the deterministic payee rule's job (M05).
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from treasurypilot_worker.agent.untrusted import sanitize

INSTRUCTION_REASON_CODE = "INSTRUCTION_TEXT"
INSTRUCTION_SEVERITY = "HIGH"
# Largest gap, in characters, between a signal and the previous one in the same match.
INSTRUCTION_MATCH_WINDOW = 150
MAX_QUOTE_CHARS = 300

_STRONG = {
    "keyword.ignore_previous": re.compile(r"\bignore\s+(?:all\s+)?previous\b", re.IGNORECASE),
    "keyword.urgent_change_of_bank": re.compile(r"\burgent\s+change\s+of\s+bank\b", re.IGNORECASE),
}
_WEAK = {
    "keyword.pay_to": re.compile(r"\bpay\s+to\b", re.IGNORECASE),
    "keyword.instead": re.compile(r"\binstead\b", re.IGNORECASE),
    "keyword.pre_approved": re.compile(r"\bpre(?:-|\s+)?approved\b", re.IGNORECASE),
}
_ADDRESS = re.compile(r"(?<![0-9A-Za-z])0x[0-9a-fA-F]{40}(?![0-9A-Za-z])")
_UNKNOWN_ADDRESS = "address.unknown"


@dataclass(frozen=True)
class InstructionMatch:
    """Signals found close together. `quote == page_text[start:end]` on the sanitised page."""

    rules: tuple[str, ...]
    quote: str
    page: int
    start: int
    end: int


@dataclass(frozen=True)
class InstructionScan:
    matches: tuple[InstructionMatch, ...]
    detector: str = "keyword_fallback"
    reduced_coverage: bool = True


@dataclass(frozen=True)
class _Signal:
    rule: str
    start: int
    end: int


def detect_instructions(
    pages: Sequence[str], *, known_addresses: Collection[str]
) -> InstructionScan:
    """Scan document pages (numbered from 1) for instruction-like text.

    Each page is sanitised first, so invisible characters cannot split a keyword.
    `known_addresses` are the payee registry's addresses; case is ignored.
    """

    known = {address.lower() for address in known_addresses}
    matches: list[InstructionMatch] = []
    for number, raw in enumerate(pages, start=1):
        text = sanitize(raw)
        for cluster in _clusters(_signals(text, known)):
            if _flagged(cluster):
                matches.append(_match(text, number, cluster))
    return InstructionScan(tuple(matches))


def _signals(text: str, known: set[str]) -> list[_Signal]:
    found = [
        _Signal(rule, m.start(), m.end())
        for rule, pattern in (_STRONG | _WEAK).items()
        for m in pattern.finditer(text)
    ]
    found += [
        _Signal(_UNKNOWN_ADDRESS, m.start(), m.end())
        for m in _ADDRESS.finditer(text)
        if m.group().lower() not in known
    ]
    return sorted(found, key=lambda s: (s.start, s.end))


def _clusters(signals: list[_Signal]) -> list[list[_Signal]]:
    clusters: list[list[_Signal]] = []
    end = 0  # furthest end in the current cluster, kept so the pass stays linear
    for signal in signals:
        if clusters and signal.start - end <= INSTRUCTION_MATCH_WINDOW:
            clusters[-1].append(signal)
            end = max(end, signal.end)
        else:
            clusters.append([signal])
            end = signal.end
    return clusters


def _flagged(cluster: list[_Signal]) -> bool:
    rules = {s.rule for s in cluster}
    return bool(rules & _STRONG.keys()) or len(rules) >= 2


def _match(text: str, page: int, cluster: list[_Signal]) -> InstructionMatch:
    first, last = cluster[0].start, max(s.end for s in cluster)
    start = text.rfind("\n", 0, first) + 1
    end = text.find("\n", last)
    end = len(text) if end == -1 else end
    if end - start > MAX_QUOTE_CHARS:
        start, end = first, min(last, first + MAX_QUOTE_CHARS)
    rules = tuple(dict.fromkeys(s.rule for s in cluster))
    return InstructionMatch(rules, text[start:end], page, start, end)
