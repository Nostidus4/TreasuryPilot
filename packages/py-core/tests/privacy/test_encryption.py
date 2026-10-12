import base64
import secrets
from pathlib import Path

import pytest

from treasurypilot_core.privacy import (
    DecryptionError,
    EncryptionConfigurationError,
    FieldCipher,
    FieldEncryptionKey,
)


def _encoded_key(byte: int = 1) -> str:
    return base64.urlsafe_b64encode(bytes([byte]) * 32).decode()


def test_encrypted_field_round_trip_is_random_and_contains_no_plaintext() -> None:
    cipher = FieldCipher(FieldEncryptionKey.from_base64(_encoded_key()))
    plaintext = "vendor@example.com / invoice 2026-0042"

    first = cipher.encrypt_text(plaintext, context="vendors.contact")
    second = cipher.encrypt_text(plaintext, context="vendors.contact")

    assert first.startswith("tpenc:v1:")
    assert first != second
    assert plaintext not in first
    assert "vendor@example.com" not in base64.urlsafe_b64decode(
        first.rsplit(":", 1)[1] + "=="
    ).decode(errors="ignore")
    assert cipher.decrypt_text(first, context="vendors.contact") == plaintext


@pytest.mark.parametrize("mutation", ["payload", "version", "key_id"])
def test_tampered_envelope_fails_closed(mutation: str) -> None:
    cipher = FieldCipher(FieldEncryptionKey.from_base64(_encoded_key()))
    envelope = cipher.encrypt_text("confidential", context="vendors.contact")
    prefix, version, key_id, payload = envelope.split(":", 3)
    if mutation == "payload":
        payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    elif mutation == "version":
        version = "v2"
    else:
        key_id = "different-key"

    with pytest.raises(DecryptionError, match="unable to decrypt field"):
        cipher.decrypt_text(f"{prefix}:{version}:{key_id}:{payload}", context="vendors.contact")


def test_wrong_key_and_wrong_context_fail_with_generic_error() -> None:
    cipher = FieldCipher(FieldEncryptionKey.from_base64(_encoded_key(1)))
    wrong_cipher = FieldCipher(FieldEncryptionKey.from_base64(_encoded_key(2)))
    envelope = cipher.encrypt_text("confidential", context="vendors.contact")

    for candidate, context in (
        (wrong_cipher, "vendors.contact"),
        (cipher, "other.column"),
    ):
        with pytest.raises(DecryptionError) as caught:
            candidate.decrypt_text(envelope, context=context)
        assert str(caught.value) == "unable to decrypt field"


def test_key_loads_from_environment_without_leaking_in_repr() -> None:
    encoded = _encoded_key()
    key = FieldEncryptionKey.from_environment(
        {"TP_FIELD_ENCRYPTION_KEY": encoded, "TP_FIELD_ENCRYPTION_KEY_ID": "primary"}
    )

    assert key.key_id == "primary"
    assert encoded not in repr(key)


def test_invalid_key_identifier_is_rejected() -> None:
    with pytest.raises(EncryptionConfigurationError):
        FieldEncryptionKey.from_base64(_encoded_key(), key_id="invalid:key-id")


def test_key_loads_from_docker_secret_file(tmp_path: Path) -> None:
    secret_file = tmp_path / "field_key"
    secret_file.write_text(_encoded_key(), encoding="utf-8")

    key = FieldEncryptionKey.from_environment({"TP_FIELD_ENCRYPTION_KEY_FILE": str(secret_file)})

    assert (
        FieldCipher(key).decrypt_text(
            FieldCipher(key).encrypt_text("safe", context="vendors.contact"),
            context="vendors.contact",
        )
        == "safe"
    )


@pytest.mark.parametrize(
    "environment",
    [
        {},
        {"TP_FIELD_ENCRYPTION_KEY": ""},
        {"TP_FIELD_ENCRYPTION_KEY": "not-base64"},
        {"TP_FIELD_ENCRYPTION_KEY": base64.b64encode(b"short").decode()},
        {"TP_FIELD_ENCRYPTION_KEY_FILE": ""},
    ],
)
def test_missing_or_invalid_configuration_fails_closed(
    environment: dict[str, str], tmp_path: Path
) -> None:
    with pytest.raises(EncryptionConfigurationError):
        FieldEncryptionKey.from_environment(environment, default_secret_path=tmp_path / "missing")


def test_unpadded_url_safe_key_is_accepted() -> None:
    # secrets.token_urlsafe(32) produces a 43-character, unpadded URL-safe
    # base64 string with no trailing "=" -- a perfectly standard key that
    # must not be rejected with "Incorrect padding".
    encoded = secrets.token_urlsafe(32)
    assert "=" not in encoded

    key = FieldEncryptionKey.from_base64(encoded)
    cipher = FieldCipher(key)

    envelope = cipher.encrypt_text("hello", context="vendors.contact")
    assert cipher.decrypt_text(envelope, context="vendors.contact") == "hello"


def test_key_rotation_decrypts_old_envelopes_and_encrypts_with_new_key() -> None:
    old_key = FieldEncryptionKey.from_base64(_encoded_key(1), key_id="k1")
    new_key = FieldEncryptionKey.from_base64(_encoded_key(2), key_id="k2")

    old_cipher = FieldCipher(old_key)
    old_envelope = old_cipher.encrypt_text("legacy value", context="vendors.contact")

    rotated_cipher = FieldCipher([new_key, old_key])

    # New writes use the new primary key.
    new_envelope = rotated_cipher.encrypt_text("fresh value", context="vendors.contact")
    assert new_envelope.split(":")[2] == "k2"
    assert rotated_cipher.decrypt_text(new_envelope, context="vendors.contact") == "fresh value"

    # Old envelopes written before rotation still decrypt.
    assert rotated_cipher.decrypt_text(old_envelope, context="vendors.contact") == "legacy value"


def test_key_rotation_rejects_unknown_key_id() -> None:
    known_key = FieldEncryptionKey.from_base64(_encoded_key(1), key_id="k1")
    unknown_key = FieldEncryptionKey.from_base64(_encoded_key(2), key_id="k2")

    unknown_cipher = FieldCipher(unknown_key)
    envelope = unknown_cipher.encrypt_text("value", context="vendors.contact")

    cipher = FieldCipher([known_key])
    with pytest.raises(DecryptionError):
        cipher.decrypt_text(envelope, context="vendors.contact")


def test_explicit_primary_key_id_selects_encryption_key() -> None:
    key_a = FieldEncryptionKey.from_base64(_encoded_key(1), key_id="k1")
    key_b = FieldEncryptionKey.from_base64(_encoded_key(2), key_id="k2")

    cipher = FieldCipher([key_a, key_b], primary_key_id="k2")
    envelope = cipher.encrypt_text("value", context="vendors.contact")

    assert envelope.split(":")[2] == "k2"


def test_context_is_required_keyword_argument() -> None:
    cipher = FieldCipher(FieldEncryptionKey.from_base64(_encoded_key()))

    with pytest.raises(TypeError):
        cipher.encrypt_text("value")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        cipher.decrypt_text("tpenc:v1:x:y")  # type: ignore[call-arg]
