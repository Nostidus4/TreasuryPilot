from __future__ import annotations

import asyncio
from typing import Any

from treasurypilot_worker.low_gas import check_low_gas


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.emitted: list[tuple[Any, ...]] = []

    async def fetch(self, sql: str, *args: Any) -> list[Any]:
        if "INSERT INTO domain_events" in sql:
            self.emitted.append(args)
            return [object()]
        return self.rows


class FakeRpc:
    def __init__(self, balance: int) -> None:
        self.balance = balance

    async def call(self, method: str, params: list[Any]) -> str:
        assert method == "eth_getBalance"
        return hex(self.balance)


def _row(address: bytes) -> dict[str, Any]:
    return {"treasury_id": "t", "org_id": "o", "from_address": address, "rpc_urls": "[]"}


def test_alert_only_below_threshold() -> None:
    rows = [_row(b"\x01" * 20), _row(b"\x02" * 20)]
    balances = {"0x" + "01" * 20: 5, "0x" + "02" * 20: 100}
    connection = FakeConnection(rows)

    class PerAddress(FakeRpc):
        async def call(self, method: str, params: list[Any]) -> str:
            return hex(balances[params[0]])

    result = asyncio.run(check_low_gas(connection, lambda urls: PerAddress(0), 10))  # type: ignore[arg-type]

    assert result == {"checked": 2, "emitted": 1}
    assert connection.emitted[0][3] == "0x" + "01" * 20
    assert '"balanceWei": "5"' in connection.emitted[0][2]


def test_low_gas_check_is_scheduled() -> None:
    from treasurypilot_worker.celery_app import app

    assert (
        app.conf.beat_schedule["check-low-gas"]["task"] == "treasurypilot.execution.check_low_gas"
    )
