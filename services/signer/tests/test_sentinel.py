from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
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
SAFE = "0x" + "a1" * 20
MODULE = "0x" + "b2" * 20
# Runtime code of tiny mocks (solc 0.8.28 --via-ir): MockModule has status()/pause() (pause only
# from `safe`); MockSafe.execTransaction requires its owner, a 65-byte v=1 signature and value 0.
MODULE_CODE = "0x6080806040526004361015610012575f80fd5b5f3560e01c908163186f03541461011057508063200d2ed2146100f15780635db0cb94146100a757638456cb5914610048575f80fd5b346100a3575f3660031901126100a3575f54600881901c6001600160a01b031633036100795760ff19166001175f55005b60405162461bcd60e51b81526020600482015260026024820152616e6f60f01b6044820152606490fd5b5f80fd5b346100a35760203660031901126100a3576004356001600160a01b03811681036100a3575f8054610100600160a81b03191660089290921b610100600160a81b0316919091179055005b346100a3575f3660031901126100a357602060ff5f5416604051908152f35b346100a3575f3660031901126100a3575f5460081c6001600160a01b03168152602090f3fea264697066735822122050fc6065006967cf924647dbdbb2785e93172358cf83a91148e0ed337d320ae264736f6c634300081c0033"
SAFE_CODE = "0x6080806040526004361015610012575f80fd5b5f3560e01c90816313af40351461022f5781636a761202146100685750638da5cb5b1461003d575f80fd5b34610064575f366003190112610064575f546040516001600160a01b039091168152602090f35b5f80fd5b34610064576101403660031901126100645761008261026b565b60443567ffffffffffffffff8111610064576100a29036906004016102ae565b9260643560ff811603610064576100b7610281565b506100c0610297565b506101243567ffffffffffffffff8111610064576100e29036906004016102ae565b5f546001600160a01b03163314919082610224575b826101f4575b5050806101ea575b156101c2575f8084868286826040519384928337810182815203925af13d156101bd573d67ffffffffffffffff81116101a95760405190601f8101601f19908116603f0116820167ffffffffffffffff8111838210176101a95760405281525f60203d92013e5b1561017c57602060405160018152f35b60405162461bcd60e51b815260206004820152600560248201526434b73732b960d91b6044820152606490fd5b634e487b7160e01b5f52604160045260245ffd5b61016c565b62461bcd60e51b815260206004820152600360248201526273696760e81b6044820152606490fd5b5060243515610105565b90915060401015610210576040013560f81c60011485806100fd565b634e487b7160e01b5f52603260045260245ffd5b6041811492506100f7565b34610064576020366003190112610064576001600160a01b0361025061026b565b166bffffffffffffffffffffffff60a01b5f5416175f555f80f35b600435906001600160a01b038216820361006457565b60e435906001600160a01b038216820361006457565b61010435906001600160a01b038216820361006457565b9181601f840112156100645782359167ffffffffffffffff831161006457602083818601950101116100645756fea26469706673582212203fab6f2f24606b12e82dc2709bc9d5c14d907cec040cbc73b22fb2c4073b46aa64736f6c634300081c0033"


def _settings(tmp_path: Path, url: str = "", *, with_targets: bool = True) -> Settings:
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
        sentinel_targets={TREASURY: {"guardianSafe": SAFE, "module": MODULE}}
        if with_targets
        else {},
    )


def _selector(signature: str, *args: Any) -> str:
    types = signature[signature.index("(") + 1 : -1]
    encoded = encode(types.split(",") if types else [], list(args))
    return "0x" + (keccak(signature.encode())[:4] + encoded).hex()


def _deploy_mocks(url: str) -> None:
    owner = _rpc(url, "eth_accounts", [])[0]
    for address, code in ((MODULE, MODULE_CODE), (SAFE, SAFE_CODE)):
        _rpc(url, "anvil_setCode", [address, code])
    _rpc(url, "anvil_setBalance", [SENTINEL.address, hex(10**18)])
    for to, data in (
        (MODULE, _selector("setSafe(address)", SAFE)),
        (SAFE, _selector("setOwner(address)", SENTINEL.address)),
    ):
        tx = _rpc(url, "eth_sendTransaction", [{"from": owner, "to": to, "data": data}])
        assert _wait_for_receipt(url, tx)["status"] == "0x1"


def _status(url: str) -> int:
    return int(_rpc(url, "eth_call", [{"to": MODULE, "data": _selector("status()")}, "latest"]), 16)


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
    _deploy_mocks(anvil_url)
    settings = _settings(tmp_path, anvil_url)
    rpc = JsonRpc(anvil_url)
    service = SentinelService(settings, rpc, SentinelKey(settings))

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
    assert _status(anvil_url) == 1
    assert receipt["to"].lower() == SAFE.lower()
    assert second == {"txHash": None, "alreadyPaused": True}
    assert int(_rpc(anvil_url, "eth_blockNumber", []), 16) == int(receipt["blockNumber"], 16)


def test_unknown_treasury_and_missing_key_are_not_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    service = SentinelService(settings, JsonRpc("http://127.0.0.1:1"), SentinelKey(settings))
    with pytest.raises(SignerFault) as unknown:
        asyncio.run(service.pause("6f0f6a2e-3b8f-4f6e-9a55-3c1d4d6a0002"))
    assert unknown.value.code == "NOT_CONFIGURED"
    bare = Settings(sentinel_targets=settings.sentinel_targets)
    with pytest.raises(SignerFault) as missing:
        asyncio.run(
            SentinelService(bare, JsonRpc("http://127.0.0.1:1"), SentinelKey(bare)).pause(TREASURY)
        )
    assert missing.value.code == "NOT_CONFIGURED"


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
