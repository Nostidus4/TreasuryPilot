from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import pytest


def load_script(name: str) -> ModuleType:
    directory = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(name, directory / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(directory), *sys.path]):
        spec.loader.exec_module(module)
    return module


def _manifest() -> dict[str, object]:
    return {
        "chainId": 11155111,
        "asset": "0x" + "11" * 20,
        "assetDecimals": 6,
        "aavePool": "0x" + "22" * 20,
        "aToken": "0x" + "33" * 20,
    }


def _mock_rpc(
    monkeypatch: pytest.MonkeyPatch,
    script: ModuleType,
    *,
    chain_id: int = 11155111,
    decimals: int = 6,
    mapped_a_token: str = "0x" + "33" * 20,
    underlying: str = "0x" + "11" * 20,
    pool: str = "0x" + "22" * 20,
    code: str = "0x6000",
    reserve_fields: int = 15,
) -> None:
    def run_cast(arguments: list[str]) -> str:
        if arguments[0] == "chain-id":
            return str(chain_id)
        if arguments[0] == "code":
            return code
        raise AssertionError(f"Unexpected cast command {arguments[0]}")

    def read_scalar(
        contract: str,
        signature: str,
        arguments: list[str],
        rpc_url: str,
        block: str = "latest",
    ) -> object:
        assert rpc_url == "https://rpc.example"
        assert block == "latest"
        if signature == "decimals()(uint8)":
            return decimals
        if signature == script._RESERVE_SIGNATURE:
            reserve: list[object] = [0] * 15
            reserve[script._RESERVE_A_TOKEN_INDEX] = mapped_a_token
            return reserve[:reserve_fields]
        if signature == "UNDERLYING_ASSET_ADDRESS()(address)":
            return underlying
        if signature == "POOL()(address)":
            return pool
        raise AssertionError(f"Unexpected RPC call {signature}")

    monkeypatch.setattr(script, "run_cast", run_cast)
    monkeypatch.setattr(script, "read_scalar", read_scalar)


def test_config_check_accepts_manifest_matching_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script("config_check")
    _mock_rpc(monkeypatch, script)

    script.check_configuration(_manifest(), "https://rpc.example")


@pytest.mark.parametrize(
    ("rpc", "error"),
    [
        ({"chain_id": 1}, "chain id"),
        ({"decimals": 18}, "decimals"),
        ({"decimals": "six"}, "Unparseable"),
        ({"code": "0x"}, "runtime code"),
        ({"reserve_fields": 14}, "invalid reserve record"),
        ({"mapped_a_token": "0x" + "77" * 20}, "reserve-to-aToken mapping"),
        ({"underlying": "0x" + "88" * 20}, "underlying"),
        ({"pool": "0x" + "99" * 20}, "Aave Pool"),
    ],
)
def test_config_check_rejects_rpc_mismatch(
    monkeypatch: pytest.MonkeyPatch, rpc: dict[str, object], error: str
) -> None:
    script = load_script("config_check")
    _mock_rpc(monkeypatch, script, **rpc)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match=error):
        script.check_configuration(_manifest(), "https://rpc.example")


def test_config_check_rejects_unpinned_a_token_before_rpc() -> None:
    script = load_script("config_check")
    manifest = _manifest()
    manifest["aToken"] = None

    with pytest.raises(ValueError, match="aToken"):
        script.check_configuration(manifest, "https://rpc.example")


def test_config_check_accepts_cast_annotated_decimals(monkeypatch: pytest.MonkeyPatch) -> None:
    script = load_script("config_check")
    _mock_rpc(monkeypatch, script, decimals="6 [6e0]")  # type: ignore[arg-type]

    script.check_configuration(_manifest(), "https://rpc.example")


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("asset", "0x" + "00" * 20, "zero address"),
        ("aavePool", "0x1234", "20-byte address"),
        ("assetDecimals", 256, "uint8"),
        ("assetDecimals", True, "uint8"),
    ],
)
def test_config_check_rejects_bad_manifest_fields(field: str, value: object, error: str) -> None:
    script = load_script("config_check")
    manifest = _manifest()
    manifest[field] = value

    with pytest.raises(ValueError, match=error):
        script.check_configuration(manifest, "https://rpc.example")


def test_config_check_requires_rpc_url_before_manifest_validation() -> None:
    script = load_script("config_check")

    with pytest.raises(ValueError, match="SEPOLIA_RPC_URL"):
        script.check_configuration({}, " ")


# Raw eth_call return data of Pool.getReserveData(Sepolia USDC), recorded 2026-10-14 from
# 0x6Ae43d3271ff6888e7Fc43Fd7321a503ff738951 (aToken is the 9th word).
_RECORDED_RESERVE_DATA = (
    "000000000000000000000103e807735940000000000003e8ad06290421341f40"
    "000000000000000000000000000000000000000009eccf5fd8e10e3b327443a7"
    "000000000000000000000000000000000000000001dc6450674d9e9a1c5c3ca7"
    "00000000000000000000000000000000000000000bb28bdc138a51f8efe98a13"
    "00000000000000000000000000000000000000000211626e6c5485c3424d8984"
    "0000000000000000000000000000000000000000021dcace0d7287afb14d8984"
    "000000000000000000000000000000000000000000000000000000006acf7754"
    "0000000000000000000000000000000000000000000000000000000000000002"
    "00000000000000000000000016da4541ad1807f4443d92d26044c1147406eb80"
    "00000000000000000000000042a218f7bd03c63c4835496506492a383efcf726"
    "00000000000000000000000036b5de936ef1710e1d22eabe5231b28581a92ecc"
    "0000000000000000000000005cb1008969a2d5face8ef32732e6a306d0d0ef2a"
    "0000000000000000000000000000000000000000000000000000840d111a6792"
    "0000000000000000000000000000000000000000000000000000000000000000"
    "0000000000000000000000000000000000000000000000000000000000000000"
)


def test_reserve_signature_matches_recorded_sepolia_output() -> None:
    from eth_abi import decode

    script = load_script("config_check")
    types = script._RESERVE_SIGNATURE.split("((", 1)[1].removesuffix("))").split(",")
    reserve = decode(types, bytes.fromhex(_RECORDED_RESERVE_DATA))

    assert len(reserve) == script._RESERVE_FIELDS
    assert (
        reserve[script._RESERVE_A_TOKEN_INDEX].lower()
        == "0x16da4541ad1807f4443d92d26044c1147406eb80"
    )
