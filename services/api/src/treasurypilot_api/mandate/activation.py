"""Build mandate activation Safe calls from the reviewed configuration diff."""

from __future__ import annotations

from datetime import UTC, datetime

from eth_abi import encode
from eth_hash.auto import keccak

from treasurypilot_api.mandate.governance import GovernanceCall


def _address(value: object) -> bytes:
    if not isinstance(value, str) or len(value) != 42 or not value.startswith("0x"):
        raise ValueError("mandate call address is invalid")
    try:
        result = bytes.fromhex(value[2:])
    except ValueError:
        raise ValueError("mandate call address is invalid") from None
    if len(result) != 20:
        raise ValueError("mandate call address is invalid")
    return result


def _optional_address(value: object) -> bytes:
    return bytes(20) if value is None else _address(value)


def _integer(value: object, name: str, bits: int = 256) -> int:
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(f"{name} must be an integer")
    if isinstance(value, str) and not (value.isascii() and value.isdecimal()):
        raise ValueError(f"{name} must be an integer")
    number = int(value)
    if number < 0:
        raise ValueError(f"{name} must not be negative")
    if number >= 1 << bits:
        raise ValueError(f"{name} must fit uint{bits}")
    return number


def _timestamp(value: object, name: str) -> int:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be a timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    result = int(parsed.astimezone(UTC).timestamp())
    if result >= 1 << 64:
        raise ValueError(f"{name} must fit uint64")
    return result


def _limits(value: object, name: str) -> tuple[int, int]:
    if value is None:
        return (0, 0)
    if not isinstance(value, dict):
        raise ValueError(f"{name} limits are missing")
    return (
        _integer(value.get("perRequest"), f"{name}.perRequest", 128),
        _integer(value.get("daily"), f"{name}.daily", 128),
    )


def _selector(signature: str) -> bytes:
    return keccak(signature.encode("ascii"))[:4]


def build_mandate_calls(
    module_address: bytes, calls: list[dict[str, object]]
) -> list[GovernanceCall]:
    """Encode the preview's calls exactly as TreasuryPilotGovernance expects them."""
    if len(module_address) != 20:
        raise ValueError("module address must be 20 bytes")
    encoded: list[GovernanceCall] = []
    for item in calls:
        method = item.get("method")
        args = item.get("arguments")
        if not isinstance(method, str) or not isinstance(args, dict):
            raise ValueError("mandate call preview is malformed")
        if method == "configureMandate":
            mandate_limits = args.get("limits") or {}
            if not isinstance(mandate_limits, dict):
                raise ValueError("mandate limits are malformed")
            pay = _limits(mandate_limits.get("PAY"), "PAY")
            refill = _limits(mandate_limits.get("REFILL"), "REFILL")
            supply = (
                _limits(args.get("supplyLimits"), "SUPPLY")
                if args.get("supplyLimits") is not None
                else (0, 0)
            )
            values = (
                _timestamp(args.get("validFrom"), "validFrom"),
                _timestamp(args.get("expiresAt"), "expiresAt"),
                _integer(args.get("payeeCoolingSeconds"), "payeeCoolingSeconds", 32),
                "0x" + _address(args.get("executor")).hex(),
                "0x" + _optional_address(args.get("guardian")).hex(),
                pay,
                refill,
                _integer(args.get("approvalMaxAge"), "approvalMaxAge", 32),
                supply,
            )
            signature = (
                "configureMandate((uint64,uint64,uint32,address,address,"
                "(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128)))"
            )
            data = _selector(signature) + encode(
                [
                    "(uint64,uint64,uint32,address,address,(uint128,uint128),"
                    "(uint128,uint128),uint32,(uint128,uint128))"
                ],
                [values],
            )
        elif method == "setBands":
            raw_bands = args.get("bands")
            if not isinstance(raw_bands, list) or not raw_bands:
                raise ValueError("approval bands are malformed")
            bands = [
                (
                    _integer(band.get("upTo"), "band upTo", 128),
                    _integer(band.get("k"), "band k", 32),
                )
                for band in raw_bands
                if isinstance(band, dict)
            ]
            if len(bands) != len(raw_bands):
                raise ValueError("approval bands are malformed")
            data = _selector("setBands((uint128,uint32)[])") + encode(
                ["(uint128,uint32)[]"], [bands]
            )
            encoded.append(GovernanceCall(_address(args.get("executor")), 0, data))
            continue
        elif method == "setApprovers":
            added, removed = args.get("add"), args.get("remove")
            if not isinstance(added, list) or not isinstance(removed, list):
                raise ValueError("approver diff is malformed")
            data = _selector("setApprovers(address[],address[])") + encode(
                ["address[]", "address[]"],
                [
                    ["0x" + _address(value).hex() for value in added],
                    ["0x" + _address(value).hex() for value in removed],
                ],
            )
        elif method == "setBuffer":
            data = _selector("setBuffer(address,uint256,uint256)") + encode(
                ["address", "uint256", "uint256"],
                [
                    "0x" + _address(args.get("wallet")).hex(),
                    _integer(args.get("minimum"), "buffer minimum"),
                    _integer(args.get("target", 0), "buffer target"),
                ],
            )
        elif method == "setAssetBuffer":
            data = _selector("setAssetBuffer(address,address,uint256,uint256)") + encode(
                ["address", "address", "uint256", "uint256"],
                [
                    "0x" + _address(args.get("asset")).hex(),
                    "0x" + _address(args.get("wallet")).hex(),
                    _integer(args.get("minimum"), "asset buffer minimum"),
                    _integer(args.get("target", 0), "asset buffer target"),
                ],
            )
        elif method == "setAssetPolicy":
            enabled = args.get("enabled")
            if not isinstance(enabled, bool):
                raise ValueError("asset policy enabled flag is malformed")
            limits = args.get("limits") if enabled else {}
            if not isinstance(limits, dict):
                raise ValueError("asset policy limits are malformed")
            pay = _limits(limits.get("PAY"), "asset PAY") if enabled else (0, 0)
            refill = _limits(limits.get("REFILL"), "asset REFILL") if enabled else (0, 0)
            data = _selector(
                "setAssetPolicy(address,bool,(uint128,uint128),(uint128,uint128))"
            ) + encode(
                ["address", "bool", "(uint128,uint128)", "(uint128,uint128)"],
                ["0x" + _address(args.get("asset")).hex(), enabled, pay, refill],
            )
        else:
            raise ValueError(f"unsupported mandate call: {method}")
        encoded.append(GovernanceCall(module_address, 0, data))
    if not encoded:
        raise ValueError("mandate diff does not contain any on-chain calls")
    return encoded
