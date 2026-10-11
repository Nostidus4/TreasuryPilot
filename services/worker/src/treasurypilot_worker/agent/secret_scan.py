"""Secret scanner for everything sent to a model (FR-804, BR-092).

Inputs that look like keys, seed phrases, signatures or credentials are rejected, never
redacted. The matched value is never kept in the error, its repr, or a log line.
"""

import os
import re
from collections.abc import Iterable, Mapping
from functools import cache
from importlib.resources import files

from treasurypilot_worker.agent.errors import AiInputRejected

_FLAGS = re.IGNORECASE

# Ordered: the first pattern that matches names the rejection.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (name, re.compile(regex, flags))
    for name, regex, flags in (
        # A. Crypto keys and signatures. A run of 64+ hex digits covers EVM private keys,
        # signature r/s values, 65-byte and concatenated Safe signatures, and long calldata.
        ("hex_key", r"(?<![0-9A-Fa-f])[0-9A-Fa-f]{64,}", 0),
        ("extended_private_key", r"\b[xtyzuv]prv[1-9A-HJ-NP-Za-km-z]{100,}", 0),
        (
            "keystore_json",
            r'"ciphertext"\s*:[\s\S]{0,2000}?"kdf"\s*:|"kdf"\s*:[\s\S]{0,2000}?"ciphertext"\s*:',
            _FLAGS,
        ),
        ("private_key_block", r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----", 0),
        # B. Service tokens.
        ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}", 0),
        ("sk_api_key", r"\bsk-[A-Za-z0-9_-]{20,}", 0),
        ("aws_access_key_id", r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", 0),
        (
            "gcp_service_account",
            r'"type"\s*:\s*"service_account"|"private_key_id"\s*:',
            0,
        ),
        ("google_api_key", r"\bAIza[0-9A-Za-z_-]{35}", 0),
        ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{36,}|\bgithub_pat_[A-Za-z0-9_]{22,}", 0),
        ("gitlab_token", r"\bglpat-[A-Za-z0-9_-]{20,}", 0),
        ("slack_token", r"\bxox[abpors]-[A-Za-z0-9-]{10,}", 0),
        ("slack_webhook", r"hooks\.slack\.com/services/[A-Za-z0-9_/]+", _FLAGS),
        ("stripe_key", r"\b(?:sk|rk)_live_[A-Za-z0-9]{16,}|\bwhsec_[A-Za-z0-9]{16,}", 0),
        ("sendgrid_key", r"\bSG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}", 0),
        ("npm_token", r"\bnpm_[A-Za-z0-9]{36,}", 0),
        ("pypi_token", r"\bpypi-[A-Za-z0-9_-]{50,}", 0),
        ("telegram_bot_token", r"\b\d{8,10}:[A-Za-z0-9_-]{35,}", 0),
        ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", 0),
        # C. Credentials in URLs and configuration.
        ("url_credentials", r"\b[a-z][a-z0-9+.-]*://[^\s/:@]*:[^\s/@]+@", _FLAGS),
        (
            "rpc_url_key",
            r"alchemy(?:api)?\.(?:com|io)/v2/[A-Za-z0-9_-]{16,}"
            r"|infura\.io/v3/[0-9a-f]{32}|quiknode\.pro/[A-Za-z0-9]{16,}",
            _FLAGS,
        ),
        (
            "authorization_header",
            r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S{8,}|\bbearer\s+[A-Za-z0-9._~+/=-]{20,}",
            _FLAGS,
        ),
        (
            "secret_assignment",
            r"\b[A-Za-z0-9_.-]*(?:key|secret|token|password|passwd|private|credential|mnemonic|seed)"
            r"[A-Za-z0-9_.-]*[\"']?\s*[:=]\s*[\"']?[^\s\"',;]{8,}",
            _FLAGS,
        ),
    )
)

MIN_MNEMONIC_WORDS = 12
# Words of a seed phrase may be separated by anything that is not a letter: whitespace,
# punctuation, list numbering or JSON syntax. Prose rarely has 12 wordlist words in a row.
_WORD = re.compile(r"[A-Za-z]+")

# Environment variables whose values are compared verbatim against every input.
_SECRET_ENV_NAME = re.compile(r"KEY|SECRET|TOKEN|PASSWORD", re.IGNORECASE)
MIN_KNOWN_SECRET_LENGTH = 16


@cache
def _bip39_words() -> frozenset[str]:
    wordlist = files("treasurypilot_worker.agent") / "data" / "bip39_english.txt"
    return frozenset(wordlist.read_text(encoding="utf-8").split())


class SecretScanner:
    def __init__(self, known_secrets: Iterable[str] = ()) -> None:
        self._known = tuple(known_secrets)

    @classmethod
    def from_environ(cls, environ: Mapping[str, str]) -> "SecretScanner":
        return cls(
            value
            for name, value in environ.items()
            if _SECRET_ENV_NAME.search(name) and len(value) >= MIN_KNOWN_SECRET_LENGTH
        )

    def find(self, text: str) -> str | None:
        """Name of the first secret pattern found in `text`, or None."""

        if any(secret in text for secret in self._known):
            return "known_secret"
        for name, pattern in _PATTERNS:
            if pattern.search(text):
                return name
        if _has_mnemonic(text):
            return "bip39_mnemonic"
        return None

    def check(self, text: str, *, source: str) -> None:
        pattern = self.find(text)
        if pattern is not None:
            raise AiInputRejected(pattern=pattern, source=source)


@cache
def default_scanner() -> SecretScanner:
    """Scanner with this process's secret values, read once from the environment."""

    return SecretScanner.from_environ(os.environ)


def _has_mnemonic(text: str) -> bool:
    words = _bip39_words()
    run = 0
    for match in _WORD.finditer(text):
        run = run + 1 if match.group().lower() in words else 0
        if run >= MIN_MNEMONIC_WORDS:
            return True
    return False
