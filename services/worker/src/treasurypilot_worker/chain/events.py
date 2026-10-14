"""The on-chain events the indexer reads, per stream (M06 §8.3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from eth_abi import decode
from eth_utils import keccak

MODULE: Final = "MODULE"
SAFE_CONFIG: Final = "SAFE_CONFIG"
SAFE_EXEC: Final = "SAFE_EXEC"


@dataclass(frozen=True)
class EventAbi:
    name: str
    topic0: str
    # ``None`` for a raw event: only its topic matters and the payload keeps topics and data.
    indexed: tuple[tuple[str, str], ...] | None
    data: tuple[tuple[str, str], ...]


def _parse(declaration: str) -> EventAbi:
    name, _, rest = declaration.partition("(")
    arguments = [part.split() for part in rest.removesuffix(")").split(",") if part.strip()]
    types = [words[0] for words in arguments]
    return EventAbi(
        name,
        "0x" + keccak(text=f"{name}({','.join(types)})").hex(),
        tuple((words[-1], words[0]) for words in arguments if "indexed" in words),
        tuple((words[-1], words[0]) for words in arguments if "indexed" not in words),
    )


def _raw(signature: str) -> EventAbi:
    return EventAbi(signature.partition("(")[0], "0x" + keccak(text=signature).hex(), None, ())


# TreasuryPilotModule (contracts/src/interfaces/ITreasuryPilotModule.sol).
_MODULE = [
    "MandateConfigured(uint64 version, uint64 expiresAt)",
    "PayeeAdded(address indexed payee, uint64 activeFrom)",
    "PayeeDeactivated(address indexed payee)",
    "ExceptionGranted(bytes32 indexed requestId, uint128 amount, address payee, "
    "uint64 expiry, uint64 version)",
    "ExceptionRevoked(bytes32 indexed requestId)",
    "Paused(address indexed by)",
    "Resumed()",
    "Revoked()",
    "RequestCancelled(bytes32 indexed requestId, address indexed by)",
    "RefillExecuted(bytes32 indexed requestId, bytes32 indexed stepId, "
    "address indexed toWallet, uint256 amount, uint256 day)",
    "PaymentExecuted(bytes32 indexed requestId, bytes32 indexed stepId, "
    "bytes32 indexed fingerprint, address payingWallet, address payee, uint256 amount, "
    "uint256 day, bool usedException, bool early)",
    "Supplied(bytes32 indexed stepId, uint256 amount, uint256 day)",
    "Withdrawn(bytes32 indexed stepId, uint256 amount, uint256 day)",
    "BorrowExecuted(bytes32 indexed planId, uint256 amount)",
    "Repaid(bytes32 indexed planId, uint256 amount)",
]

# Safe 1.4.1 configuration events stay raw: indexed-ness differs across Safe versions and the
# indexer only needs to know that something changed.
_SAFE_CONFIG = [
    _raw(signature)
    for signature in (
        "AddedOwner(address)",
        "RemovedOwner(address)",
        "ChangedThreshold(uint256)",
        "EnabledModule(address)",
        "DisabledModule(address)",
        "ChangedGuard(address)",
        "ChangedFallbackHandler(address)",
    )
]

_SAFE_EXEC = [
    "ExecutionSuccess(bytes32 indexed txHash, uint256 payment)",
    "ExecutionFailure(bytes32 indexed txHash, uint256 payment)",
]

EVENTS: Final[Mapping[str, Mapping[str, EventAbi]]] = {
    stream: {abi.topic0: abi for abi in abis}
    for stream, abis in {
        MODULE: [_parse(item) for item in _MODULE],
        SAFE_CONFIG: _SAFE_CONFIG,
        SAFE_EXEC: [_parse(item) for item in _SAFE_EXEC],
    }.items()
}


def decode_log(abi: EventAbi, log: Mapping[str, Any]) -> dict[str, Any]:
    """Decode one ``eth_getLogs`` entry; integers become strings (uint256 exceeds JSON)."""

    topics = [str(topic) for topic in log["topics"]]
    data = str(log["data"])
    if abi.indexed is None:
        return {"topics": topics[1:], "data": data}
    payload = {
        name: _plain(decode([kind], bytes.fromhex(topic[2:]))[0])
        for (name, kind), topic in zip(abi.indexed, topics[1:], strict=True)
    }
    if abi.data:
        values = decode([kind for _, kind in abi.data], bytes.fromhex(data[2:]))
        payload |= {name: _plain(value) for (name, _), value in zip(abi.data, values, strict=True)}
    return payload


def _plain(value: Any) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return str(value)
    if isinstance(value, bytes):
        return "0x" + value.hex()
    return str(value).lower()
