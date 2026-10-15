from __future__ import annotations

import asyncio
import uuid
from typing import Any

from eth_abi import encode

from treasurypilot_worker.chain.event_handlers import IndexedEvent, _token_transfer
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
