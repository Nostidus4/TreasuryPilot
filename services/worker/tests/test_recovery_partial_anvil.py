"""AT-07: a refill mined, the pay blocked, then resumed on Anvil sends only the pay (RCV-003)."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config

from treasurypilot_core.policy import PolicyReasonCode
from treasurypilot_worker.tracker import track_transactions

# Tests run in importlib mode, so sibling modules are loaded by path.
_HERE = Path(__file__).parent


def _load(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_seq = _load("sequencer_fixtures", _HERE / "executor" / "test_sequencer_integration.py")
_trk = _load("tracker_fixtures", _HERE / "test_tracker_integration.py")
anvil_url = _trk.anvil_url  # pytest fixture, reused as is

REFILL_TO = "0x" + "33" * 20
PAY_TO = "0x" + "44" * 20


class AnvilSigner:
    """Broadcasts a real transfer per step; replays by step id like the real signer."""

    def __init__(self, url: str, targets: dict[str, tuple[str, int]]) -> None:
        self.url, self.targets = url, targets  # step id -> (recipient, wei)
        self.sent: dict[str, dict[str, Any]] = {}

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        key = request["plan"]["steps"][request["stepSeq"]]["stepId"]
        if key not in self.sent:
            to, wei = self.targets[key]
            nonce = int(
                _trk._rpc(self.url, "eth_getTransactionCount", [_trk.SENDER, "pending"]), 16
            )
            tx_hash = _trk._send(self.url, to=to, value=hex(wei), nonce=hex(nonce))
            self.sent[key] = {"txHash": tx_hash, "nonce": nonce, "from": _trk.SENDER}
        return self.sent[key]


@pytest.fixture(scope="module")
def database_url() -> Iterator[str]:
    if "TP_TEST_DATABASE_URL" not in os.environ:
        pytest.skip("TP_TEST_DATABASE_URL is required for the AT-07 test")
    url = os.environ["TP_TEST_DATABASE_URL"]
    config = Config(str(_seq.API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_seq.API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        asyncio.run(_seq._seed(url))
        yield url
    finally:
        command.downgrade(config, "base")


def _balance(url: str, address: str) -> int:
    return int(_trk._rpc(url, "eth_getBalance", [address, "latest"]), 16)


async def _confirm_on_chain(url: str, database_url: str) -> None:
    _trk._mine(url, 5)  # the chain row requires 3 confirmations
    await track_transactions(database_url, client_factory=lambda _urls: _trk._client(url))


def test_at07_resume_after_blocked_pay_sends_only_the_pay(
    anvil_url: str, database_url: str
) -> None:
    async def scenario() -> None:
        run = await _seq._new_run(database_url)
        refill, pay = run.steps
        signer = AnvilSigner(
            anvil_url,
            {
                "0x" + refill.step_id.hex(): (REFILL_TO, 1000),
                "0x" + pay.step_id.hex(): (PAY_TO, 7),
            },
        )
        gate = _seq.FakeGate()
        await _seq._sql(
            database_url,
            "INSERT INTO plans (id, org_id, treasury_id, request_id, status) "
            "VALUES ($1, $2, $3, $4, 'Executing')",
            run.plan_id,
            uuid.UUID(_seq._ORG),
            _seq._TREASURY,
            run.request_id,
        )
        refill_before, pay_before = _balance(anvil_url, REFILL_TO), _balance(anvil_url, PAY_TO)

        # The refill is mined and confirmed by the real tracker.
        assert (await _seq._go(database_url, signer, run, gate)).status == "Waiting"
        await _confirm_on_chain(anvil_url, database_url)
        # The pay is blocked by policy: the plan stops partially completed.
        gate.verdict = _seq._decision("BLOCK", PolicyReasonCode.SOURCE_BUFFER_BREACH)
        assert (await _seq._go(database_url, signer, run, gate)).status == "PartiallyCompleted"
        await _seq._sql(
            database_url,
            "UPDATE plans SET status = 'PartiallyCompleted' WHERE id = $1",
            run.plan_id,
        )
        assert _balance(anvil_url, REFILL_TO) == refill_before + 1000
        assert _balance(anvil_url, PAY_TO) == pay_before  # nothing paid yet
        assert len(signer.sent) == 1

        # Resume: the block is lifted; only the pay is validated and sent.
        assert (await _seq._resume(database_url, run.request_id)).status == "Resumed"
        gate.checked.clear()
        gate.verdict = _seq._decision("ALLOW")
        assert (await _seq._go(database_url, signer, run, gate)).status == "Waiting"
        await _confirm_on_chain(anvil_url, database_url)
        assert (await _seq._go(database_url, signer, run, gate)).status == "Completed"

        assert gate.checked == [1]
        assert len(signer.sent) == 2
        assert _balance(anvil_url, REFILL_TO) == refill_before + 1000  # exactly one refill
        assert _balance(anvil_url, PAY_TO) == pay_before + 7
        ops = await _seq._sql(
            database_url,
            "SELECT kind::text AS kind, status::text AS status FROM operations "
            "WHERE request_id = $1 ORDER BY created_at",
            run.request_id,
        )
        assert [(o["kind"], o["status"]) for o in ops] == [
            ("REFILL", "Confirmed"),
            ("PAY", "Confirmed"),
        ]
        status = await _seq._sql(
            database_url, "SELECT status FROM payment_requests WHERE id = $1", run.request_id
        )
        assert status[0]["status"] == "Paid"

    asyncio.run(scenario())
