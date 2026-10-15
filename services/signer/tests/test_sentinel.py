from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pytest
from eth_abi import encode
from eth_account import Account
from eth_hash.auto import keccak
from fastapi.testclient import TestClient

from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import SentinelKey
from treasurypilot_signer.main import create_app
from treasurypilot_signer.rpc import JsonRpc
from treasurypilot_signer.sentinel import SentinelService, build_pause_transaction
from treasurypilot_signer.service import SignerFault

# pytest runs in importlib mode, so sibling test modules are loaded by path.
_spec = importlib.util.spec_from_file_location(
    "signing_fixtures", Path(__file__).with_name("test_signing.py")
)
assert _spec is not None and _spec.loader is not None
_signing = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_signing)
anvil_url = _signing.anvil_url
_rpc, _wait_for_receipt = _signing._rpc, _signing._wait_for_receipt  # noqa: SLF001

SENTINEL = Account.from_key(bytes(31) + b"\x0a")
PASSWORD = "sentinel-password"
TREASURY = "6f0f6a2e-3b8f-4f6e-9a55-3c1d4d6a0001"
SECRET = "shared-secret"
SAFE = "0x" + "a1" * 20  # placeholder targets for tests that never reach a chain
MODULE = "0x" + "b2" * 20
_OUT = Path(__file__).resolve().parents[3] / "contracts" / "out"
_ZERO = "0x" + "00" * 20


def _settings(
    tmp_path: Path,
    url: str = "",
    *,
    with_targets: bool = True,
    safe: str = SAFE,
    module: str = MODULE,
) -> Settings:
    keystore = tmp_path / "sentinel.json"
    keystore.write_text(json.dumps(Account.encrypt(SENTINEL.key, PASSWORD, iterations=2)))
    password = tmp_path / "sentinel-password"
    password.write_text(PASSWORD)
    return Settings(
        allowed_chain_ids=[31337],
        signer_shared_secret=SECRET,
        chain_rpc_url=url,
        sentinel_keystore_path=keystore,
        sentinel_keystore_password_file=password,
        sentinel_targets={TREASURY: {"guardianSafe": safe, "module": module}}
        if with_targets
        else {},
    )


def _selector(signature: str, *args: Any) -> str:
    inner, depth, types, start = signature[signature.index("(") + 1 : -1], 0, [], 0
    for index, char in enumerate(inner):  # split on top-level commas only (tuples nest)
        depth += (char == "(") - (char == ")")
        if char == "," and depth == 0:
            types.append(inner[start:index])
            start = index + 1
    types += [inner[start:]] if inner else []
    return "0x" + (keccak(signature.encode())[:4] + encode(types, list(args))).hex()


@pytest.fixture(autouse=True)
def _require_anvil() -> None:
    if os.environ.get("TP_REQUIRE_SENTINEL_ANVIL") == "1" and shutil.which("anvil") is None:
        pytest.fail("anvil is required for the sentinel integration test")


def _artifacts() -> dict[str, str]:
    required = os.environ.get("TP_REQUIRE_SENTINEL_ANVIL") == "1"
    try:
        names = (
            "Safe",
            "SafeProxyFactory",
            "TestUSDC",
            "TreasuryPilotModule",
            "TreasuryPilotModuleFactory",
        )
        return {
            name: json.loads((_OUT / f"{name}.sol" / f"{name}.json").read_text())["bytecode"][
                "object"
            ]
            for name in names
        }
    except (OSError, KeyError) as error:
        reason = f"run `forge build` in contracts/ for the sentinel integration test: {error}"
        if required:
            pytest.fail(reason)
        pytest.skip(reason)


def _send(url: str, sender: str, to: str | None, data: bytes) -> dict[str, Any]:
    tx = {"from": sender, "data": "0x" + data.hex(), "gas": hex(25_000_000)}
    if to:
        tx["to"] = to
    receipt = _wait_for_receipt(url, _rpc(url, "eth_sendTransaction", [tx]))
    assert receipt["status"] == "0x1", receipt
    return receipt


def _data(signature: str, *args: Any) -> bytes:
    return bytes.fromhex(_selector(signature, *args)[2:])


def _safe_proxy(url: str, deployer: str, singleton: str, factory: str, owner: str) -> str:
    setup = _data(
        "setup(address[],uint256,address,bytes,address,address,uint256,address)",
        [owner],
        1,
        _ZERO,
        b"",
        _ZERO,
        _ZERO,
        0,
        _ZERO,
    )
    salt = time.time_ns()
    create = _data("createProxyWithNonce(address,bytes,uint256)", singleton, setup, salt)
    proxy = _rpc(
        url, "eth_call", [{"from": deployer, "to": factory, "data": "0x" + create.hex()}, "latest"]
    )
    _send(url, deployer, factory, create)
    return "0x" + proxy[-40:]


def _deploy_treasury(url: str) -> tuple[str, str]:
    """A real Safe 1.4.1 guardian owned by the sentinel and a real module that names it guardian."""
    code = _artifacts()
    owner = _rpc(url, "eth_accounts", [])[0]  # anvil's unlocked account owns the treasury Safes
    deployed = {
        name: _send(url, owner, None, bytes.fromhex(code[name].removeprefix("0x")))[
            "contractAddress"
        ]
        for name in ("Safe", "SafeProxyFactory", "TestUSDC", "TreasuryPilotModule")
    }
    proxy_factory = deployed["SafeProxyFactory"]
    safe_t, operational = (
        _safe_proxy(url, owner, deployed["Safe"], proxy_factory, owner) for _ in range(2)
    )
    guardian = _safe_proxy(url, owner, deployed["Safe"], proxy_factory, SENTINEL.address)
    module_factory = _send(
        url,
        owner,
        None,
        bytes.fromhex(code["TreasuryPilotModuleFactory"].removeprefix("0x"))
        + encode(["address"], [deployed["TreasuryPilotModule"]]),
    )["contractAddress"]
    limits = (10**6, 10**7)
    mandate = (1, 2**40, 300, owner, guardian, limits, limits, 3600, (0, 0))
    salt = time.time_ns().to_bytes(32, "big")
    create = _data(
        "createDeterministic(address,address[],"
        "(uint64,uint64,uint32,address,address,(uint128,uint128),(uint128,uint128),uint32,"
        "(uint128,uint128)),address[],(address,uint256,uint256)[],address,bytes32)",
        deployed["TestUSDC"],
        [operational],
        mandate,
        [owner],
        [(safe_t, 0, 0), (operational, 0, 0)],
        _ZERO,
        salt,
    )
    # safeT.execTransaction(...) approved by msg.sender (v=1), as the owner
    approval = bytes(12) + bytes.fromhex(owner[2:]) + bytes(32) + b"\x01"
    _send(
        url,
        owner,
        safe_t,
        _data(
            "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,"
            "address,bytes)",
            module_factory,
            0,
            create,
            0,
            0,
            0,
            0,
            _ZERO,
            _ZERO,
            approval,
        ),
    )
    module = _rpc(
        url,
        "eth_call",
        [
            {
                "to": module_factory,
                "data": _selector("predictDeterministicAddress(address,bytes32)", safe_t, salt),
            },
            "latest",
        ],
    )
    module = "0x" + module[-40:]
    assert _rpc(url, "eth_getCode", [module, "latest"]) != "0x"
    _rpc(url, "anvil_setBalance", [SENTINEL.address, hex(10**18)])
    return guardian, module


def _status(url: str, module: str) -> int:
    return int(_rpc(url, "eth_call", [{"to": module, "data": _selector("status()")}, "latest"]), 16)


def test_pause_calldata_is_exactly_execute_pause_on_the_module() -> None:
    data = build_pause_transaction(SENTINEL.address, MODULE)
    assert (
        data[:4]
        == keccak(
            b"execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)"
        )[:4]
    )
    assert keccak(b"pause()")[:4].hex() in data.hex()
    assert MODULE[2:] in data.hex()


def test_pause_lands_within_two_blocks_and_is_idempotent_on_anvil(
    anvil_url: str, tmp_path: Path
) -> None:
    guardian, module = _deploy_treasury(anvil_url)
    assert _status(anvil_url, module) == 0
    settings = _settings(tmp_path, anvil_url, safe=guardian, module=module)
    rpc = JsonRpc(anvil_url)
    service = SentinelService(settings, rpc, SentinelKey(settings).load())

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            return await service.pause(TREASURY), await service.pause(TREASURY)
        finally:
            await rpc.close()

    start = int(_rpc(anvil_url, "eth_blockNumber", []), 16)
    first, second = asyncio.run(run())

    receipt = _wait_for_receipt(anvil_url, first["txHash"])
    assert receipt["status"] == "0x1"
    assert int(receipt["blockNumber"], 16) - start <= 2
    assert _status(anvil_url, module) == 1  # Status.Paused
    assert receipt["to"].lower() == guardian.lower()
    assert second == {"txHash": None, "alreadyPaused": True}
    assert int(_rpc(anvil_url, "eth_blockNumber", []), 16) == int(receipt["blockNumber"], 16)


def test_unknown_treasury_is_not_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = SentinelService(settings, JsonRpc("http://127.0.0.1:1"), SENTINEL)
    with pytest.raises(SignerFault) as unknown:
        asyncio.run(service.pause("6f0f6a2e-3b8f-4f6e-9a55-3c1d4d6a0002"))
    assert unknown.value.code == "NOT_CONFIGURED"


def test_targets_without_rpc_url_refuse_to_start(tmp_path: Path) -> None:
    with (
        pytest.raises(RuntimeError, match="CHAIN_RPC_URL"),
        TestClient(create_app(settings_override=_settings(tmp_path))),
    ):
        pass


@pytest.mark.parametrize(
    "target",
    [
        {"guardianSafe": _ZERO, "module": MODULE},
        {"guardianSafe": SAFE, "module": _ZERO},
        {"guardianSafe": SAFE, "module": SAFE},
    ],
)
def test_bad_sentinel_targets_are_rejected(target: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="sentinel"):
        Settings(sentinel_targets={TREASURY: target})


def test_endpoint_refuses_extra_fields_and_requires_the_secret(tmp_path: Path) -> None:
    settings = _settings(tmp_path, "http://127.0.0.1:1")
    with TestClient(create_app(settings_override=settings)) as client:
        body = {"treasuryId": TREASURY}
        assert client.post("/sentinel/pause", json=body).status_code == 401
        headers = {"X-Signer-Secret": SECRET}
        for extra in ({"to": SAFE}, {"data": "0x"}, {"calldata": "0x"}):
            assert (
                client.post("/sentinel/pause", json={**body, **extra}, headers=headers).status_code
                == 422
            )
        assert client.get("/sentinel/address").json() == {"address": SENTINEL.address}
        assert client.get("/health").json()["sentinel"]["address"] == SENTINEL.address


def test_sentinel_is_off_without_targets_and_refuses_a_bad_password(tmp_path: Path) -> None:
    off = _settings(tmp_path, "http://127.0.0.1:1", with_targets=False)
    with TestClient(create_app(settings_override=off)) as client:
        assert client.get("/sentinel/address").status_code == 503
        headers = {"X-Signer-Secret": SECRET}
        pause = client.post("/sentinel/pause", json={"treasuryId": TREASURY}, headers=headers)
        assert pause.json() == {"code": "NOT_CONFIGURED"}
    bad = _settings(tmp_path, "http://127.0.0.1:1")
    assert bad.sentinel_keystore_password_file is not None
    bad.sentinel_keystore_password_file.write_text("wrong")
    with pytest.raises(Exception), TestClient(create_app(settings_override=bad)):  # noqa: B017, PT011
        pass


def test_sentinel_key_never_reaches_logs_or_health(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = _settings(tmp_path, "http://127.0.0.1:1")
    with TestClient(create_app(settings_override=settings)) as client:
        client.post(
            "/sentinel/pause", json={"treasuryId": TREASURY}, headers={"X-Signer-Secret": SECRET}
        )
        text = client.get("/health").text + client.get("/sentinel/address").text
    secret = SENTINEL.key.hex().removeprefix("0x")
    for output in (caplog.text, text):
        assert secret not in output.lower()
        assert PASSWORD not in output
