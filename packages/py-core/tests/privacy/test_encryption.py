import base64
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

    assert FieldCipher(key).decrypt_text(FieldCipher(key).encrypt_text("safe")) == "safe"


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
