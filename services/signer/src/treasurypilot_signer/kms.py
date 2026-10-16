"""AWS KMS signing backend for the executor key (ADR-006, EXE-L01).

The key is an asymmetric ``ECC_SECG_P256K1`` key with ``KeyUsage=SIGN_VERIFY``. KMS never exports
the private key; it signs a 32-byte digest (``MessageType=DIGEST``, ``ECDSA_SHA_256`` algorithm
identifier, which for DIGEST means "sign these bytes as-is") and returns an ASN.1 DER signature.
We convert that to ``(r, s, v)``: ``s`` is normalised to the lower half of the curve order and
``v`` (the recovery id) is found by recovering the public key and matching it to the KMS key.
"""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable
from typing import Any, Protocol, cast

from eth_account._utils.legacy_transactions import (
    encode_transaction,
    serializable_unsigned_transaction_from_dict,
)
from eth_account.datastructures import SignedTransaction
from eth_keys import keys
from eth_utils import keccak, to_checksum_address
from hexbytes import HexBytes

logger = logging.getLogger(__name__)

SECP256K1_ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
_HALF_ORDER = SECP256K1_ORDER // 2
# id-ecPublicKey and secp256k1 (1.3.132.0.10), DER-encoded OIDs without tag and length.
_OID_EC_PUBLIC_KEY = bytes.fromhex("2a8648ce3d0201")
_OID_SECP256K1 = bytes.fromhex("2b8104000a")
_TRANSIENT_CODES = frozenset(
    {
        "ThrottlingException",
        "KMSInternalException",
        "DependencyTimeoutException",
        "InternalFailure",
        "ServiceUnavailable",
        "RequestTimeout",
    }
)
_TRANSIENT_NAMES = frozenset(
    {"ConnectTimeoutError", "ReadTimeoutError", "EndpointConnectionError", "ConnectionClosedError"}
)


class KmsSigningError(RuntimeError):
    """KMS could not produce a usable key or signature. Messages never carry key identifiers."""


class KmsClient(Protocol):
    """The two boto3 ``kms`` client calls the signer needs (lets tests inject a fake)."""

    def get_public_key(self, *, KeyId: str) -> dict[str, Any]: ...  # noqa: N803

    def sign(
        self,
        *,
        KeyId: str,  # noqa: N803
        Message: bytes,  # noqa: N803
        MessageType: str,  # noqa: N803
        SigningAlgorithm: str,  # noqa: N803
    ) -> dict[str, Any]: ...


class ExecutorSigner(Protocol):
    """What the signing service needs from an executor key, whatever backs it."""

    @property
    def address(self) -> str: ...

    def sign_transaction(self, transaction_dict: Any) -> Any: ...


# --- DER helpers ---------------------------------------------------------------------------


def _read_tlv(data: bytes, offset: int, expected_tag: int) -> tuple[bytes, int]:
    if offset + 2 > len(data) or data[offset] != expected_tag:
        raise ValueError("unexpected DER tag")
    length = data[offset + 1]
    offset += 2
    if length & 0x80:
        count = length & 0x7F
        if count == 0 or count > 2 or offset + count > len(data):
            raise ValueError("bad DER length")
        length = int.from_bytes(data[offset : offset + count], "big")
        offset += count
    end = offset + length
    if end > len(data):
        raise ValueError("truncated DER")
    return data[offset:end], end


def public_key_from_spki(spki: bytes) -> bytes:
    """Return the 64-byte uncompressed (x || y) secp256k1 key from a SubjectPublicKeyInfo."""
    try:
        body, end = _read_tlv(spki, 0, 0x30)
        if end != len(spki):
            raise ValueError("trailing bytes")
        algorithm, pos = _read_tlv(body, 0, 0x30)
        bit_string, pos = _read_tlv(body, pos, 0x03)
        if pos != len(body):
            raise ValueError("trailing bytes")
        algorithm_oid, apos = _read_tlv(algorithm, 0, 0x06)
        curve_oid, apos = _read_tlv(algorithm, apos, 0x06)
        if apos != len(algorithm):
            raise ValueError("trailing bytes")
    except ValueError as error:
        raise KmsSigningError("KMS public key is not a valid SubjectPublicKeyInfo") from error
    if algorithm_oid != _OID_EC_PUBLIC_KEY or curve_oid != _OID_SECP256K1:
        raise KmsSigningError("KMS key is not an ECC_SECG_P256K1 key")
    if len(bit_string) != 66 or bit_string[0] != 0 or bit_string[1] != 0x04:
        raise KmsSigningError("KMS public key is not an uncompressed secp256k1 point")
    point = bit_string[2:]
    try:
        keys.PublicKey(point)  # validates the point is on the curve
    except Exception as error:
        raise KmsSigningError("KMS public key is not a valid secp256k1 point") from error
    return point


def address_from_public_key(public_key: bytes) -> str:
    return to_checksum_address(keccak(public_key)[-20:])


def parse_der_signature(der: bytes) -> tuple[int, int]:
    try:
        body, end = _read_tlv(der, 0, 0x30)
        if end != len(der):
            raise ValueError("trailing bytes")
        r_bytes, pos = _read_tlv(body, 0, 0x02)
        s_bytes, pos = _read_tlv(body, pos, 0x02)
        if pos != len(body):
            raise ValueError("trailing bytes")
    except ValueError as error:
        raise KmsSigningError("KMS returned a malformed signature") from error
    r, s = int.from_bytes(r_bytes, "big"), int.from_bytes(s_bytes, "big")
    if not (0 < r < SECP256K1_ORDER and 0 < s < SECP256K1_ORDER):
        raise KmsSigningError("KMS returned an out-of-range signature")
    return r, s


def normalise_low_s(s: int) -> int:
    return SECP256K1_ORDER - s if s > _HALF_ORDER else s


def recover_v(message_hash: bytes, r: int, s: int, expected_public_key: bytes) -> int:
    """Return the recovery id (0 or 1) whose recovered key equals ``expected_public_key``."""
    for v in (0, 1):
        try:
            signature = keys.Signature(vrs=(v, r, s))
            recovered = signature.recover_public_key_from_msg_hash(message_hash)
        except Exception:  # noqa: S112 - an invalid candidate is simply not the match
            continue
        if recovered.to_bytes() == expected_public_key:
            return v
    raise KmsSigningError("KMS signature does not recover to the KMS public key")


# --- retries ---------------------------------------------------------------------------------


def _is_transient(error: Exception) -> bool:
    if isinstance(error, TimeoutError | ConnectionError):
        return True
    if type(error).__name__ in _TRANSIENT_NAMES:
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        return code in _TRANSIENT_CODES
    return False


def _with_retries[T](
    operation: Callable[[], T],
    *,
    what: str,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Callable[[float], None],
) -> T:
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as error:
            if attempt < max_attempts and _is_transient(error):
                # Log the exception type only: provider messages can embed key ARNs.
                logger.warning(
                    "KMS %s failed (%s), retrying (%d/%d)",
                    what,
                    type(error).__name__,
                    attempt,
                    max_attempts,
                )
                sleep(backoff_seconds * 2 ** (attempt - 1))
                continue
            logger.error("KMS %s failed (%s)", what, type(error).__name__)
            raise KmsSigningError(f"KMS {what} failed") from None
    raise AssertionError("unreachable")  # pragma: no cover


# --- account ---------------------------------------------------------------------------------


class KmsAccount:
    """An executor account whose private key lives in KMS."""

    def __init__(
        self,
        client: KmsClient,
        key_id: str,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._key_id = key_id
        self._max_attempts = max(1, max_attempts)
        self._backoff = backoff_seconds
        self._sleep = sleep
        response = self._call(
            "get_public_key", lambda: self._client.get_public_key(KeyId=self._key_id)
        )
        self._public_key = public_key_from_spki(bytes(response["PublicKey"]))
        self._address = address_from_public_key(self._public_key)

    def _call[T](self, what: str, operation: Callable[[], T]) -> T:
        return _with_retries(
            operation,
            what=what,
            max_attempts=self._max_attempts,
            backoff_seconds=self._backoff,
            sleep=self._sleep,
        )

    @property
    def address(self) -> str:
        return self._address

    def sign_digest(self, digest: bytes) -> tuple[int, int, int]:
        """Sign a 32-byte digest; returns ``(v, r, s)`` with ``v`` in {0, 1} and low ``s``."""
        if len(digest) != 32:
            raise KmsSigningError("digest must be 32 bytes")
        response = self._call(
            "sign",
            lambda: self._client.sign(
                KeyId=self._key_id,
                Message=digest,
                MessageType="DIGEST",
                SigningAlgorithm="ECDSA_SHA_256",
            ),
        )
        r, s = parse_der_signature(bytes(response["Signature"]))
        s = normalise_low_s(s)
        return recover_v(digest, r, s, self._public_key), r, s

    def sign_transaction(self, transaction_dict: dict[str, Any]) -> SignedTransaction:
        transaction = dict(transaction_dict)
        sender = transaction.pop("from", None)
        if sender is not None and str(sender).lower() != self._address.lower():
            raise KmsSigningError("transaction sender does not match the KMS key")
        unsigned = serializable_unsigned_transaction_from_dict(cast(Any, transaction))
        v, r, s = self.sign_digest(bytes(unsigned.hash()))
        encoded = encode_transaction(unsigned, vrs=(v, r, s))
        return SignedTransaction(
            raw_transaction=HexBytes(encoded),
            hash=HexBytes(keccak(encoded)),
            r=r,
            s=s,
            v=v,
        )


def build_kms_client(
    *, region: str | None, endpoint_url: str | None, timeout_seconds: float
) -> KmsClient:
    """Create a boto3 KMS client (boto3 is installed only in KMS deployments, not a default dependency).

    Credentials come from the standard AWS chain (instance/task role); none are configured here.
    Retries are handled by ``KmsAccount`` so boto's own are disabled to avoid multiplying them.
    """
    try:
        boto3 = importlib.import_module("boto3")
        botocore_config = importlib.import_module("botocore.config")
    except ImportError as error:
        raise KmsSigningError(
            "the KMS backend needs boto3; install boto3 in the signer image"
        ) from error
    config = botocore_config.Config(
        connect_timeout=timeout_seconds,
        read_timeout=timeout_seconds,
        retries={"max_attempts": 0},
    )
    return cast(
        KmsClient,
        boto3.client("kms", region_name=region, endpoint_url=endpoint_url, config=config),
    )
