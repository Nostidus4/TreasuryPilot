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
) -> None:
    def run_cast(arguments: list[str]) -> str:
        if arguments[0] == "chain-id":
            return str(chain_id)
        if arguments[0] == "code":
            return "0x6000"
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
            return [
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                mapped_a_token,
                "0x" + "44" * 20,
                "0x" + "55" * 20,
                "0x" + "66" * 20,
                0,
                0,
                0,
            ]
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
