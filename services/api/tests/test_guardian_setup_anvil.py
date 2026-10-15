"""Guardian Safe setup with the sentinel on Anvil and PostgreSQL (MDT-010)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from eth_abi import encode
from eth_account import Account
from eth_utils import keccak

from treasurypilot_api.config import Settings
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.mandate.guardian import router as guardian_router
from treasurypilot_api.treasury.safe import RpcSafeVerifier
from treasurypilot_api.treasury.service import TreasuryService
from treasurypilot_api.treasury.sync import asset_id

# pytest runs in importlib mode, so sibling test modules are loaded by path.
_spec = importlib.util.spec_from_file_location(
    "treasury_setup_fixtures", Path(__file__).with_name("test_treasury_setup_anvil.py")
)
assert _spec is not None and _spec.loader is not None
_setup = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_setup)
anvil_url = _setup.anvil_url
_rpc = _setup._rpc  # noqa: SLF001

SENTINEL = Account.from_key(bytes(31) + b"\x0b")
SECRET = "guardian-test-secret"
ZERO = "0x" + "00" * 20
PROXY_CREATION = "0x" + keccak(text="ProxyCreation(address,address)").hex()


class _Signer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        ok = self.path == "/sentinel/address" and self.headers.get("X-Signer-Secret") == SECRET
        body = json.dumps({"address": SENTINEL.address} if ok else {"code": "UNAUTHORIZED"})
        self.send_response(200 if ok else 401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *_: Any) -> None:
        return None


def _selector(signature: str, *types_and_args: Any) -> str:
    types, args = types_and_args[0], types_and_args[1:]
    return "0x" + (keccak(text=signature)[:4] + encode(types, list(args))).hex()


def _approved(owner: str) -> bytes:
    """Safe signature 'approved by msg.sender' (v=1) for a 1-of-N Safe."""
    return bytes(12) + bytes.fromhex(owner[2:]) + bytes(32) + b"\x01"


def _exec_data(to: str, data: bytes, owner: str) -> str:
    return _selector(
        "execTransaction(address,uint256,bytes,uint8,uint256,uint256,uint256,address,address,bytes)",
        [
            "address",
            "uint256",
            "bytes",
            "uint8",
            "uint256",
            "uint256",
            "uint256",
            "address",
            "address",
            "bytes",
        ],
        to,
        0,
        data,
        0,
        0,
        0,
        0,
        ZERO,
        ZERO,
        _approved(owner),
    )


def _status(url: str, module: str) -> int:
    return int(
        _rpc(url, "eth_call", [{"to": module, "data": _selector("status()", [])}, "latest"]), 16
    )


def _guardian_exec(url: str, safe: str, sender: str, to: str, data: bytes) -> dict[str, Any]:
    tx = {"from": sender, "to": safe, "data": _exec_data(to, data, sender), "gas": "0x989680"}
    return _wait(url, _rpc(url, "eth_sendTransaction", [tx]))


def _wait(url: str, tx_hash: str) -> dict[str, Any]:
    for _ in range(50):
        receipt = _rpc(url, "eth_getTransactionReceipt", [tx_hash])
        if receipt is not None:
            return receipt  # type: ignore[no-any-return]
        time.sleep(0.1)
    raise AssertionError(f"transaction {tx_hash} was not mined")


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for the PostgreSQL guardian integration",
)
def test_guardian_safe_setup_sentinel_pause_human_pause_and_removal(
    anvil_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _setup._deploy_fixture(anvil_url)  # noqa: SLF001
    configuration = _setup._configuration(anvil_url, fixture)  # noqa: SLF001
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    alembic = _setup._alembic_config(database_url)  # noqa: SLF001
    # The CI job shares one database with the owner-setup test, which leaves its rows behind.
    command.downgrade(alembic, "base")
    command.upgrade(alembic, "head")
    engine, sessions = asyncio.run(_setup._prepare_database(database_url, configuration))  # noqa: SLF001
    verifier = RpcSafeVerifier(configuration, {})
    org = _setup.ORG_ID
    human = _setup.OWNER

    server = HTTPServer(("127.0.0.1", 0), _Signer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    client = _setup._client(  # noqa: SLF001
        monkeypatch,
        TreasuryService(sessions, verifier, configuration),
        GovernanceService(sessions, verifier, configuration, {}),
        configuration,
    )
    client.app.include_router(guardian_router)  # type: ignore[attr-defined]
    client.app.state.request_sessions = sessions  # type: ignore[attr-defined]
    client.app.state.settings = Settings(  # type: ignore[attr-defined]
        signer_url=f"http://127.0.0.1:{server.server_port}", signer_shared_secret=SECRET
    )
    _rpc(anvil_url, "anvil_setBalance", [SENTINEL.address, hex(10**18)])
    try:
        created = client.post(
            f"/v1/orgs/{org}/treasuries",
            json={
                "chainId": _setup.CHAIN_ID,
                "assetId": str(asset_id(_setup.CHAIN_ID, fixture["token"])),
                "wallets": [
                    {"role": "SOURCE", "safeAddress": fixture["safeT"], "label": "T"},
                    {"role": "OPERATIONAL", "safeAddress": fixture["safeO1"], "label": "O1"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        treasury_id = created.json()["treasury"]["id"]
        base = f"/v1/orgs/{org}/treasuries/{treasury_id}/guardian"

        assert client.get(f"{base}/health").json()["warnings"][0]["code"] == "GUARDIAN_NOT_SET_UP"

        # The sentinel can never be listed as a human guardian, and a bad address is refused.
        assert (
            client.post(f"{base}/setup-tx", json={"humanOwners": [SENTINEL.address]}).status_code
            == 422
        )
        built = client.post(f"{base}/setup-tx", json={"humanOwners": [human]})
        assert built.status_code == 200, built.text
        assert built.json()["threshold"] == 1
        assert built.json()["owners"] == [human, SENTINEL.address]
        tx = built.json()["transaction"]

        # A Safe that is not the Guardian Safe (threshold 2 or no sentinel) is not recorded.
        wrong = client.post(f"{base}/confirm", json={"guardianSafe": fixture["safeT"]})
        assert wrong.status_code == 422, wrong.text

        receipt = _wait(
            anvil_url,
            _rpc(
                anvil_url,
                "eth_sendTransaction",
                [{"from": human, "to": tx["to"], "data": tx["data"], "gas": "0x989680"}],
            ),
        )
        assert receipt["status"] == "0x1"
        log = next(item for item in receipt["logs"] if item["topics"][0] == PROXY_CREATION)
        guardian_safe = "0x" + log["topics"][1][-40:]

        confirmed = client.post(f"{base}/confirm", json={"guardianSafe": guardian_safe})
        assert confirmed.status_code == 201, confirmed.text
        assert confirmed.json()["mandateGuardian"] == guardian_safe.lower()
        assert (
            client.post(f"{base}/confirm", json={"guardianSafe": guardian_safe}).status_code == 201
        )

        healthy = client.get(f"{base}/health").json()
        assert healthy["sentinelIsOwner"] is True
        assert healthy["hasGas"] is True
        assert healthy["automaticPauseAvailable"] is True
        assert healthy["warnings"] == []

        # Module setup defaults its guardian to the recorded Guardian Safe.
        now = datetime.now(UTC)
        setup = client.post(
            f"/v1/orgs/{org}/treasuries/{treasury_id}/module/deploy-tx",
            json={
                "mandate": {
                    "validFrom": (now - timedelta(minutes=1)).isoformat(),
                    "expiresAt": (now + timedelta(days=7)).isoformat(),
                    "payeeCoolingSeconds": 60,
                    "executor": human,
                    "guardian": None,
                    "pay": {"perRequest": "0", "daily": "0"},
                    "refill": {"perRequest": "0", "daily": "0"},
                    "supply": {"perRequest": "0", "daily": "0"},
                    "approvalMaxAge": 86400,
                    "approvers": [human],
                },
                "buffers": [
                    {"wallet": fixture["safeT"], "minimum": "0", "target": "0"},
                    {"wallet": fixture["safeO1"], "minimum": "0", "target": "0"},
                ],
            },
        )
        assert setup.status_code == 201, setup.text
        for governance_tx in [
            setup.json()["governanceTx"],
            *setup.json()["operationalGovernanceTxs"],
        ]:
            _setup._execute_setup_transaction(client, anvil_url, governance_tx, org)  # noqa: SLF001
        module = client.get(f"/v1/orgs/{org}/treasuries/{treasury_id}").json()["treasury"][
            "moduleAddress"
        ]
        pause = keccak(text="pause()")[:4]

        snapshot = _rpc(anvil_url, "evm_snapshot", [])
        _rpc(anvil_url, "anvil_impersonateAccount", [SENTINEL.address])
        assert (
            _guardian_exec(anvil_url, guardian_safe, SENTINEL.address, module, pause)["status"]
            == "0x1"
        )
        assert _status(anvil_url, module) == 1  # the sentinel paused through the Guardian Safe
        assert _rpc(anvil_url, "evm_revert", [snapshot]) is True

        snapshot = _rpc(anvil_url, "evm_snapshot", [])
        assert _guardian_exec(anvil_url, guardian_safe, human, module, pause)["status"] == "0x1"
        assert _status(anvil_url, module) == 1  # a human guardian paused from their wallet
        assert _rpc(anvil_url, "evm_revert", [snapshot]) is True

        # The human removes the sentinel: automatic pause is gone and the health check says so.
        owners = healthy["onchainOwners"]
        previous = (
            "0x" + "00" * 19 + "01"
            if owners[0].lower() == SENTINEL.address.lower()
            else owners[owners.index(SENTINEL.address) - 1]
        )
        remove = bytes.fromhex(
            _selector(
                "removeOwner(address,address,uint256)",
                ["address", "address", "uint256"],
                previous,
                SENTINEL.address,
                1,
            )[2:]
        )
        assert (
            _guardian_exec(anvil_url, guardian_safe, human, guardian_safe, remove)["status"]
            == "0x1"
        )
        degraded = client.get(f"{base}/health").json()
        assert degraded["sentinelIsOwner"] is False
        assert degraded["automaticPauseAvailable"] is False
        assert [item["code"] for item in degraded["warnings"]] == ["SENTINEL_NOT_OWNER"]
        rejected = _guardian_exec(anvil_url, guardian_safe, SENTINEL.address, module, pause)
        assert rejected["status"] == "0x0"  # the Safe no longer accepts the sentinel
        assert _status(anvil_url, module) == 0
    finally:
        server.shutdown()
        asyncio.run(engine.dispose())
