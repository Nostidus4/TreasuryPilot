"""Authenticated field encryption for Confidential database columns.

The serialized envelope is safe to store in a text column.  Key material is
provided by configuration at runtime and never serialized with the envelope.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_ENVELOPE_PREFIX = "tpenc"
_ENVELOPE_VERSION = "v1"
_NONCE_BYTES = 12
_KEY_BYTES = 32
_DEFAULT_SECRET_PATH = Path("/run/secrets/field_key")
_KEY_ID = re.compile(r"[A-Za-z0-9._-]{1,64}\Z")


class EncryptionConfigurationError(RuntimeError):
    """Raised when field encryption cannot be configured safely."""


class DecryptionError(ValueError):
    """Raised for every invalid envelope without exposing failure details."""


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value, altchars=b"-_", validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EncryptionConfigurationError("field encryption key is invalid") from exc


@dataclass(frozen=True, slots=True)
class FieldEncryptionKey:
    """An AES-256 key plus its non-secret rotation identifier."""

    key_id: str
    _material: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if len(self._material) != _KEY_BYTES:
            raise EncryptionConfigurationError("field encryption key must be 256 bits")
        if not _KEY_ID.fullmatch(self.key_id):
            raise EncryptionConfigurationError("field encryption key id is invalid")

    @classmethod
    def from_base64(cls, encoded: str, *, key_id: str | None = None) -> FieldEncryptionKey:
        """Parse a URL-safe or standard base64-encoded 256-bit key."""

        if not encoded or not encoded.strip():
            raise EncryptionConfigurationError("field encryption key is missing")
        material = _decode_base64(encoded.strip())
        derived_id = hashlib.sha256(material).hexdigest()[:16]
        return cls(key_id=key_id or derived_id, _material=material)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        key_variable: str = "TP_FIELD_ENCRYPTION_KEY",
        key_file_variable: str = "TP_FIELD_ENCRYPTION_KEY_FILE",
        key_id_variable: str = "TP_FIELD_ENCRYPTION_KEY_ID",
        default_secret_path: Path = _DEFAULT_SECRET_PATH,
    ) -> FieldEncryptionKey:
        """Load a key from configuration or a Docker secret, failing closed.

        Direct key configuration is useful for managed secret injection.  If it
        is absent, the configured file path (or ``/run/secrets/field_key``) is
        read.  An explicitly configured but blank value is rejected.
        """

        values = os.environ if environment is None else environment
        key_id = values.get(key_id_variable) or None

        if key_variable in values:
            return cls.from_base64(values[key_variable], key_id=key_id)

        configured_path = values.get(key_file_variable)
        if configured_path is not None and not configured_path.strip():
            raise EncryptionConfigurationError("field encryption key file is missing")
        key_path = Path(configured_path) if configured_path else default_secret_path
        try:
            encoded = key_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EncryptionConfigurationError("field encryption key is unavailable") from exc
        return cls.from_base64(encoded, key_id=key_id)


class FieldCipher:
    """Encrypt and decrypt field values with AES-256-GCM."""

    def __init__(self, encryption_key: FieldEncryptionKey) -> None:
        self._key_id = encryption_key.key_id
        self._cipher = AESGCM(encryption_key._material)

    @staticmethod
    def _metadata(key_id: str) -> bytes:
        return f"{_ENVELOPE_PREFIX}:{_ENVELOPE_VERSION}:{key_id}".encode()

    @classmethod
    def _associated_data(cls, key_id: str, context: bytes) -> bytes:
        metadata = cls._metadata(key_id)
        return len(metadata).to_bytes(2, "big") + metadata + context

    def encrypt(self, plaintext: bytes, *, context: bytes = b"") -> str:
        """Return a versioned, authenticated envelope for arbitrary bytes."""

        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(
            nonce,
            plaintext,
            self._associated_data(self._key_id, context),
        )
        payload = base64.urlsafe_b64encode(nonce + ciphertext).decode().rstrip("=")
        return f"{_ENVELOPE_PREFIX}:{_ENVELOPE_VERSION}:{self._key_id}:{payload}"

    def encrypt_text(self, plaintext: str, *, context: str = "") -> str:
        """Encrypt UTF-8 text for a Confidential text column."""

        return self.encrypt(plaintext.encode(), context=context.encode())

    def decrypt(self, envelope: str, *, context: bytes = b"") -> bytes:
        """Decrypt an envelope or raise the same error for every failure mode."""

        try:
            prefix, version, key_id, encoded_payload = envelope.split(":", 3)
            if prefix != _ENVELOPE_PREFIX or version != _ENVELOPE_VERSION:
                raise ValueError
            if key_id != self._key_id:
                raise ValueError
            padding = "=" * (-len(encoded_payload) % 4)
            payload = base64.b64decode(
                encoded_payload + padding,
                altchars=b"-_",
                validate=True,
            )
            if len(payload) < _NONCE_BYTES + 16:
                raise ValueError
            nonce, ciphertext = payload[:_NONCE_BYTES], payload[_NONCE_BYTES:]
            return self._cipher.decrypt(
                nonce,
                ciphertext,
                self._associated_data(key_id, context),
            )
        except (InvalidTag, ValueError, binascii.Error, UnicodeError):
            raise DecryptionError("unable to decrypt field") from None

    def decrypt_text(self, envelope: str, *, context: str = "") -> str:
        """Decrypt a UTF-8 text envelope."""

        try:
            return self.decrypt(envelope, context=context.encode()).decode()
        except UnicodeError:
            raise DecryptionError("unable to decrypt field") from None
