from __future__ import annotations

import asyncio
import json
from typing import Any

from treasurypilot_worker.celery_app import app
from treasurypilot_worker.low_gas import check_low_gas

A, B = "0x" + "01" * 20, "0x" + "02" * 20


class FakeConnection:
    def __init__(self, senders: list[bytes]) -> None:
        self.senders = senders
        self.emitted: list[tuple[Any, ...]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        if "INSERT INTO domain_events" in sql:
            self.emitted.append(args)
            return [object()]
        return [{"treasury_id": "t", "org_id": "o", "rpc_urls": "[]", "senders": self.senders}]

    async def execute(self, sql: str, *args: Any) -> None:
        pass

    def transaction(self) -> Any:
        class Tx:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, *exc: object) -> None:
                return None

        return Tx()


def _rpc_for(balances: dict[str, int | Exception]) -> Any:
    class Rpc:
        async def call(self, method: str, params: list[Any]) -> str:
            assert method == "eth_getBalance"
            balance = balances[params[0]]
            if isinstance(balance, Exception):
                raise balance
            return hex(balance)

    return lambda urls: Rpc()


def _run(connection: FakeConnection, balances: dict[str, Any], configured: Any = ()) -> Any:
    return asyncio.run(check_low_gas(connection, _rpc_for(balances), 10, configured))  # type: ignore[arg-type]


def test_alert_only_below_threshold() -> None:
    connection = FakeConnection([b"\x01" * 20, b"\x02" * 20])

    result = _run(connection, {A: 5, B: 100})

    assert result == {"checked": 2, "emitted": 1, "failed": 0}
    assert connection.emitted[0][3] == A
    assert '"balanceWei": "5"' in connection.emitted[0][2]


def test_configured_addresses_are_swept_with_their_role_without_any_tx() -> None:
    connection = FakeConnection([])

    result = _run(
        connection, {A: 1, B: 2}, [("executor", A.upper()), ("sentinel", B), ("receipt", None)]
    )

    assert result["emitted"] == 2
    roles = [json.loads(event[2])["role"] for event in connection.emitted]
    assert roles == ["executor", "sentinel"]


def test_one_failing_address_does_not_stop_the_sweep() -> None:
    connection = FakeConnection([b"\x01" * 20, b"\x02" * 20])

    result = _run(connection, {A: RuntimeError("rpc down"), B: 1})

    assert result == {"checked": 1, "emitted": 1, "failed": 1}
    assert connection.emitted[0][3] == B


def test_low_gas_check_runs_every_five_minutes() -> None:
    entry = app.conf.beat_schedule["check-low-gas"]
    assert entry["task"] == "treasurypilot.execution.check_low_gas"
    assert entry["schedule"].total_seconds() == 300
