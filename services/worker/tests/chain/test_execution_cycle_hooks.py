from __future__ import annotations

import asyncio
import uuid
from typing import Any

from eth_abi import encode

from treasurypilot_worker.chain.event_handlers import (
    IndexedEvent,
    _exception_granted,
    _payee_added,
    _resumed,
    _token_transfer,
)
from treasurypilot_worker.chain.events import EVENTS, TOKEN, decode_log


class _Connection:
    def __init__(self, destination_is_wallet: bool) -> None:
        self.destination_is_wallet = destination_is_wallet
        self.inserted: list[tuple[Any, ...]] = []

    async def fetchval(self, _query: str, *_args: object) -> bool:
        return self.destination_is_wallet

    async def execute(self, _query: str, *args: object) -> str:
        self.inserted.append(args)
        return "INSERT 0 1"


def _transfer_event(sender: bytes, recipient: bytes, value: int) -> IndexedEvent:
    abi = next(iter(EVENTS[TOKEN].values()))
    log = {
        "topics": [
            abi.topic0,
            "0x" + encode(["address"], [sender]).hex(),
            "0x" + encode(["address"], [recipient]).hex(),
        ],
        "data": "0x" + encode(["uint256"], [value]).hex(),
    }
    treasury_id = uuid.uuid4()
    return IndexedEvent(
        treasury_id=treasury_id,
        chain_id=1,
        stream=TOKEN,
        name="Transfer",
        address=bytes.fromhex("11" * 20),
        tx_hash=bytes.fromhex("22" * 32),
        log_index=0,
        block_number=10,
        payload=decode_log(abi, log),
    )


def test_erc20_transfer_to_treasury_wallet_enqueues_execution_cycle() -> None:
    connection = _Connection(destination_is_wallet=True)
    event = _transfer_event(bytes.fromhex("33" * 20), bytes.fromhex("44" * 20), 100)

    asyncio.run(_token_transfer(connection, event))  # type: ignore[arg-type]

    assert len(connection.inserted) == 1
    assert connection.inserted[0][0] == event.treasury_id


def test_zero_transfer_is_ignored_and_non_wallet_target_is_ignored() -> None:
    external_transfer = _Connection(destination_is_wallet=False)
    zero_transfer = _transfer_event(bytes.fromhex("33" * 20), bytes.fromhex("44" * 20), 0)
    wallet_transfer = _transfer_event(bytes.fromhex("33" * 20), bytes.fromhex("44" * 20), 1)

    asyncio.run(_token_transfer(external_transfer, zero_transfer))  # type: ignore[arg-type]
    asyncio.run(_token_transfer(external_transfer, wallet_transfer))  # type: ignore[arg-type]

    assert external_transfer.inserted == []


class _Hook:
    """Connection whose conditional UPDATE returns `row`; INSERTs are the enqueue."""

    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.inserted: list[tuple[Any, ...]] = []

    async def fetchrow(self, _query: str, *_args: object) -> dict[str, Any] | None:
        return self.row

    async def execute(self, query: str, *args: object) -> str:
        if "ExecutionCycleRequested" in query:
            self.inserted.append(args)
        return "OK"


def _event(name: str, payload: dict[str, Any]) -> IndexedEvent:
    return IndexedEvent(
        treasury_id=uuid.uuid4(),
        chain_id=1,
        stream="MODULE",
        name=name,
        address=bytes.fromhex("11" * 20),
        tx_hash=bytes.fromhex("22" * 32),
        log_index=0,
        block_number=10,
        payload=payload,
    )


def test_resume_enqueues_only_when_a_pause_was_cleared() -> None:
    event = _event("Resumed", {})
    cleared, untouched = _Hook({"treasury_id": event.treasury_id}), _Hook(None)

    asyncio.run(_resumed(cleared, event))  # type: ignore[arg-type]
    asyncio.run(_resumed(untouched, event))  # type: ignore[arg-type]

    assert [args[0] for args in cleared.inserted] == [event.treasury_id]
    assert untouched.inserted == []


def test_exception_granted_enqueues_for_the_matching_proposal_only() -> None:
    request_id = uuid.uuid4()
    event = _event(
        "ExceptionGranted",
        {
            "requestId": "0x" + "01" * 32,
            "payee": "0x" + "02" * 20,
            "amount": "5",
            "version": 1,
            "expiry": 1_900_000_000,
        },
    )
    matched, mismatched = _Hook({"request_id": request_id}), _Hook(None)

    asyncio.run(_exception_granted(matched, event))  # type: ignore[arg-type]
    asyncio.run(_exception_granted(mismatched, event))  # type: ignore[arg-type]

    assert [args[0] for args in matched.inserted] == [event.treasury_id]
    assert matched.inserted[0][2] == request_id
    assert mismatched.inserted == []


def test_payee_added_enqueues_only_when_it_is_already_active() -> None:
    event = _event("PayeeAdded", {"payee": "0x" + "02" * 20, "activeFrom": 1})
    active, cooling = _Hook({"status": "Active"}), _Hook({"status": "Cooling"})

    asyncio.run(_payee_added(active, event))  # type: ignore[arg-type]
    asyncio.run(_payee_added(cooling, event))  # type: ignore[arg-type]

    assert len(active.inserted) == 1
    assert cooling.inserted == []
