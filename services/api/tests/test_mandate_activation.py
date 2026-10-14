from __future__ import annotations

from eth_abi import decode
from eth_hash.auto import keccak

from treasurypilot_api.mandate.activation import build_mandate_calls
from treasurypilot_api.mandate.configuration import build_bundle_preview


SAFE = "0x" + "11" * 20
OPERATIONAL = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
APPROVER = "0x" + "44" * 20
GUARDIAN = "0x" + "55" * 20
MODULE = bytes.fromhex("66" * 20)


def config() -> dict[str, object]:
    return {
        "actions": ["PAY", "REFILL", "SUPPLY"],
        "refillPaths": [{"from": SAFE, "to": OPERATIONAL}],
        "limits": {
            "PAY": {"perRequest": "200", "daily": "1000"},
            "REFILL": {"perRequest": "250", "daily": "1200"},
        },
        "supplyLimits": {"perRequest": "500", "daily": "2000"},
        "buffers": [
            {"wallet": SAFE, "minimum": "10"},
            {"wallet": OPERATIONAL, "minimum": "20", "target": "150"},
        ],
        "executor": EXECUTOR,
        "approvers": [APPROVER],
        "guardian": GUARDIAN,
        "validFrom": "2030-01-01T00:00:00Z",
        "expiresAt": "2030-02-01T00:00:00Z",
        "payeeCoolingSeconds": 300,
        "approvalMaxAge": 1200,
    }


def test_buffer_only_mandate_change_does_not_encode_configure_mandate() -> None:
    previous = config()
    current = config() | {
        "buffers": [
            {"wallet": SAFE, "minimum": "10"},
            {"wallet": OPERATIONAL, "minimum": "25", "target": "150"},
        ]
    }
    preview = build_bundle_preview(previous, current)

    encoded = build_mandate_calls(MODULE, preview["calls"])

    assert len(encoded) == 1
    assert encoded[0].to == MODULE
    assert encoded[0].data[:4] == keccak(b"setBuffer(address,uint256,uint256)")[:4]


def test_configure_mandate_encoding_includes_supply_limits() -> None:
    preview = build_bundle_preview(None, config())

    encoded = build_mandate_calls(MODULE, preview["calls"])
    selector = keccak(
        b"configureMandate((uint64,uint64,uint32,address,address,"
        b"(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128)))"
    )[:4]
    argument = decode(
        [
            "(uint64,uint64,uint32,address,address,(uint128,uint128),"
            "(uint128,uint128),uint32,(uint128,uint128))"
        ],
        encoded[0].data[4:],
    )[0]

    assert encoded[0].data[:4] == selector
    assert argument[5] == (200, 1000)
    assert argument[6] == (250, 1200)
    assert argument[8] == (500, 2000)


def test_empty_mandate_diff_is_rejected() -> None:
    try:
        build_mandate_calls(MODULE, [])
    except ValueError as exc:
        assert "does not contain" in str(exc)
    else:
        raise AssertionError("empty mandate call list should fail")
