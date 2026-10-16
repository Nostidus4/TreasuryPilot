from __future__ import annotations

import logging
from typing import Any

import pytest
from eth_account import Account
from eth_keys import keys
from eth_utils import keccak

from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import ExecutorKeyNotConfigured, ExecutorKeys, ExecutorKeyUnavailable
from treasurypilot_signer.kms import (
    SECP256K1_ORDER,
    KmsAccount,
    KmsSigningError,
    address_from_public_key,
    normalise_low_s,
    parse_der_signature,
    public_key_from_spki,
)

# Anvil account #0: a well-known public test key and address.
PRIVATE_KEY = bytes.fromhex("ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80")
EXPECTED_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
_SPKI_PREFIX = bytes.fromhex("3056301006072a8648ce3d020106052b8104000a0342")


def _der_int(value: int) -> bytes:
    raw = value.to_bytes((value.bit_length() + 7) // 8 or 1, "big")
    if raw[0] & 0x80:
        raw = b"\x00" + raw
    return b"\x02" + bytes([len(raw)]) + raw


def _der_signature(r: int, s: int) -> bytes:
    body = _der_int(r) + _der_int(s)
    return b"\x30" + bytes([len(body)]) + body


class ClientError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(f"{code}: arn:aws:kms:secret-key-arn")
        self.response = {"Error": {"Code": code}}


class FakeKms:
    """A KMS stand-in backed by a local secp256k1 key; optionally returns high-s signatures."""

    def __init__(self, private_key: bytes = PRIVATE_KEY, *, high_s: bool = False) -> None:
        self._key = keys.PrivateKey(private_key)
        self._high_s = high_s
        self.failures: list[Exception] = []
        self.sign_calls: list[dict[str, Any]] = []
        self.public_key_calls = 0

    def get_public_key(self, *, KeyId: str) -> dict[str, Any]:  # noqa: N803
        self.public_key_calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {"PublicKey": _SPKI_PREFIX + b"\x00\x04" + self._key.public_key.to_bytes()}

    def sign(
        self,
        *,
        KeyId: str,  # noqa: N803
        Message: bytes,  # noqa: N803
        MessageType: str,  # noqa: N803
        SigningAlgorithm: str,  # noqa: N803
    ) -> dict[str, Any]:
        self.sign_calls.append({"MessageType": MessageType, "SigningAlgorithm": SigningAlgorithm})
        if self.failures:
            raise self.failures.pop(0)
        signature = self._key.sign_msg_hash(Message)
        s = signature.s
        if self._high_s and s <= SECP256K1_ORDER // 2:
            s = SECP256K1_ORDER - s
        return {"Signature": _der_signature(signature.r, s)}


def _account(client: FakeKms, **kwargs: Any) -> KmsAccount:
    return KmsAccount(client, "alias/executor", sleep=lambda _: None, **kwargs)


def test_address_is_derived_from_the_spki_public_key() -> None:
    assert _account(FakeKms()).address == EXPECTED_ADDRESS


def test_spki_rejects_wrong_curve_and_garbage() -> None:
    spki = _SPKI_PREFIX + b"\x00\x04" + keys.PrivateKey(PRIVATE_KEY).public_key.to_bytes()
    assert address_from_public_key(public_key_from_spki(spki)) == EXPECTED_ADDRESS
    p256 = spki.replace(bytes.fromhex("2b8104000a"), bytes.fromhex("2a8648ce3d030107"))
    for bad in (b"", b"\x30\x00", spki[:-1], p256):
        with pytest.raises(KmsSigningError):
            public_key_from_spki(bad)


def test_der_parsing_and_low_s() -> None:
    assert parse_der_signature(_der_signature(5, 7)) == (5, 7)
    with pytest.raises(KmsSigningError):
        parse_der_signature(b"\x30\x03\x02\x01")
    with pytest.raises(KmsSigningError):
        parse_der_signature(_der_signature(0, 7))
    assert normalise_low_s(SECP256K1_ORDER - 3) == 3
    assert normalise_low_s(3) == 3


@pytest.mark.parametrize("high_s", [False, True])
def test_signature_is_low_s_and_recovers_to_the_expected_address(high_s: bool) -> None:
    account = _account(FakeKms(high_s=high_s))
    for i in range(20):  # covers both recovery ids and both s halves
        digest = keccak(f"message-{i}".encode())
        v, r, s = account.sign_digest(digest)
        assert v in (0, 1)
        assert s <= SECP256K1_ORDER // 2
        recovered = keys.Signature(vrs=(v, r, s)).recover_public_key_from_msg_hash(digest)
        assert recovered.to_checksum_address() == EXPECTED_ADDRESS


def test_known_vector_signed_transaction_recovers_to_executor() -> None:
    transaction = {
        "chainId": 31337,
        "from": EXPECTED_ADDRESS,
        "to": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "value": 1,
        "data": b"",
        "nonce": 7,
        "gas": 21000,
        "maxFeePerGas": 2_000_000_000,
        "maxPriorityFeePerGas": 1_000_000_000,
        "type": 2,
    }
    signed = _account(FakeKms(high_s=True)).sign_transaction(transaction)
    assert Account.recover_transaction(signed.raw_transaction) == EXPECTED_ADDRESS
    # Same unsigned tx signed locally is deterministic (RFC 6979), so the bytes must match.
    local = Account.sign_transaction(
        {k: v for k, v in transaction.items() if k != "from"}, PRIVATE_KEY
    )
    assert bytes(signed.raw_transaction) == bytes(local.raw_transaction)
    assert bytes(signed.hash) == bytes(local.hash)


def test_sender_mismatch_is_refused() -> None:
    with pytest.raises(KmsSigningError):
        _account(FakeKms()).sign_transaction(
            {"from": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8", "chainId": 1}
        )


def test_kms_uses_digest_mode() -> None:
    client = FakeKms()
    _account(client).sign_digest(keccak(b"x"))
    assert client.sign_calls == [{"MessageType": "DIGEST", "SigningAlgorithm": "ECDSA_SHA_256"}]


def test_transient_failures_are_retried_then_succeed() -> None:
    client = FakeKms()
    client.failures = [ClientError("ThrottlingException"), TimeoutError()]
    assert _account(client, max_attempts=3).address == EXPECTED_ADDRESS
    assert client.public_key_calls == 3


def test_permanent_failure_is_not_retried_and_does_not_leak(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = FakeKms()
    client.failures = [ClientError("AccessDeniedException")]
    with caplog.at_level(logging.DEBUG), pytest.raises(KmsSigningError) as raised:
        _account(client)
    assert client.public_key_calls == 1
    assert "arn:aws" not in str(raised.value)
    assert "arn:aws" not in caplog.text
    assert "ClientError" in caplog.text


def test_retries_are_bounded() -> None:
    client = FakeKms()
    client.failures = [TimeoutError()] * 5
    with pytest.raises(KmsSigningError):
        _account(client, max_attempts=2)
    assert client.public_key_calls == 2


def test_wrong_key_signature_is_rejected() -> None:
    class Mismatched(FakeKms):
        def sign(self, **kwargs: Any) -> dict[str, Any]:
            other = keys.PrivateKey(b"\x11" * 32).sign_msg_hash(kwargs["Message"])
            return {"Signature": _der_signature(other.r, other.s)}

    with pytest.raises(KmsSigningError):
        _account(Mismatched()).sign_digest(keccak(b"x"))


def _settings(**kwargs: Any) -> Settings:
    return Settings(
        executor_key_backend="kms",
        executor_kms_key_map={"Treasury-1": "alias/executor"},
        **kwargs,
    )


def test_backend_defaults_to_keystore() -> None:
    assert Settings().executor_key_backend == "keystore"
    assert not ExecutorKeys(Settings()).configured


def test_kms_backend_selected_by_config_and_validated() -> None:
    client = FakeKms()
    keys_ = ExecutorKeys(_settings(), kms_client_factory=lambda: client)
    assert keys_.configured
    assert keys_.validate() == {"treasury-1": EXPECTED_ADDRESS}
    assert keys_.for_treasury("TREASURY-1").address == EXPECTED_ADDRESS
    assert client.public_key_calls == 1  # cached
    with pytest.raises(ExecutorKeyNotConfigured):
        keys_.for_treasury("other")


def test_kms_failure_surfaces_as_unavailable() -> None:
    client = FakeKms()
    client.failures = [ClientError("AccessDeniedException")]
    with pytest.raises(ExecutorKeyUnavailable):
        ExecutorKeys(_settings(), kms_client_factory=lambda: client).validate()


def test_kms_key_map_parses_json_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TP_EXECUTOR_KEY_BACKEND", "kms")
    monkeypatch.setenv("TP_EXECUTOR_KMS_KEY_MAP", '{"t1": "alias/x"}')
    settings = Settings()
    assert settings.executor_key_backend == "kms"
    assert settings.executor_kms_key_map == {"t1": "alias/x"}
