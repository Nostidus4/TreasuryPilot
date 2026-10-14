from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

TOKEN = "0x" + "aa" * 20
ALICE = "0x" + "11" * 20
BOB = "0x" + "22" * 20
TX = "0x" + "01" * 32


def load_logic() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "onchain_reconcile" / "logic.py"
    spec = importlib.util.spec_from_file_location("onchain_reconcile_logic", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


logic = load_logic()


def topic(address: str) -> str:
    return "0x" + "00" * 12 + address[2:]


def make_log(
    sender: str = ALICE, to: str = BOB, amount: int = 500, tx: str = TX, index: int = 0
) -> dict[str, Any]:
    return {
        "address": TOKEN.upper().replace("0X", "0x"),
        "topics": [logic.TRANSFER_TOPIC, topic(sender), topic(to)],
        "data": hex(amount),
        "transactionHash": tx,
        "logIndex": hex(index),
    }


def make_receipt(status: int = 1, block: int = 10, logs: list[Any] | None = None) -> dict[str, Any]:
    return {
        "status": hex(status),
        "blockNumber": hex(block),
        "to": TOKEN,
        "logs": [make_log()] if logs is None else logs,
    }


def make_row(**overrides: Any) -> Any:
    values: dict[str, Any] = {
        "kind": "transfer",
        "status": "confirmed",
        "tx_hash": TX,
        "block_number": 10,
        "from_addr": ALICE,
        "to_addr": BOB,
        "amount": 500,
    }
    values.update(overrides)
    return logic.Row(**values)


def test_matching_receipt_has_no_problems() -> None:
    assert logic.compare_receipt(make_row(), make_receipt(), TOKEN) == []


def test_mint_expects_zero_sender() -> None:
    row = make_row(kind="mint", from_addr=BOB)
    receipt = make_receipt(logs=[make_log(sender=logic.ZERO_ADDRESS)])
    assert logic.compare_receipt(row, receipt, TOKEN) == []


def test_amount_mismatch_is_exact_integer() -> None:
    problems = logic.compare_receipt(make_row(amount=501), make_receipt(), TOKEN)
    assert problems == ["amount db=501 chain=500"]


def test_block_and_status_mismatch() -> None:
    problems = logic.compare_receipt(make_row(), make_receipt(status=0, block=11), TOKEN)
    assert "status db=confirmed chain=failed" in problems
    assert "block db=10 chain=11" in problems


def test_recipient_mismatch() -> None:
    problems = logic.compare_receipt(make_row(to_addr=ALICE), make_receipt(), TOKEN)
    assert problems == [f"to db={ALICE} chain={BOB}"]


def test_missing_receipt_and_missing_tx_hash() -> None:
    assert logic.compare_receipt(make_row(), None, TOKEN) == ["receipt missing on chain"]
    pending = make_row(status="pending", tx_hash=None, block_number=None)
    assert logic.compare_receipt(pending, None, TOKEN) == ["no tx_hash (status=pending)"]


def test_zero_or_duplicate_transfer_logs_are_flagged() -> None:
    assert "0 Transfer logs (want 1)" in logic.compare_receipt(
        make_row(), make_receipt(logs=[]), TOKEN
    )
    two = make_receipt(logs=[make_log(), make_log(index=1)])
    assert "2 Transfer logs (want 1)" in logic.compare_receipt(make_row(), two, TOKEN)


def test_logs_from_other_contracts_are_ignored() -> None:
    other = make_log()
    other["address"] = "0x" + "bb" * 20
    receipt = make_receipt(logs=[other, make_log()])
    assert logic.compare_receipt(make_row(), receipt, TOKEN) == []


def test_orphan_log_without_row() -> None:
    log = logic.parse_transfer_log(make_log(tx="0x" + "02" * 32, amount=424242))
    orphans = logic.find_orphans([make_row()], [log])
    assert orphans == [(log, "no DB row for tx")]


def test_log_that_disagrees_with_row() -> None:
    log = logic.parse_transfer_log(make_log(amount=499))
    assert logic.find_orphans([make_row()], [log]) == [(log, "DB row differs from log")]


def test_matching_logs_have_no_orphans() -> None:
    log = logic.parse_transfer_log(make_log())
    assert logic.find_orphans([make_row(), make_row(tx_hash=None)], [log]) == []


def test_parse_transfer_log_uses_integer_amount() -> None:
    parsed = logic.parse_transfer_log(make_log(amount=2**200))
    assert parsed.amount == 2**200
    assert parsed.from_addr == ALICE and parsed.to_addr == BOB


def test_block_ranges_chunk_inclusively() -> None:
    assert logic.block_ranges(5, 4) == []
    assert logic.block_ranges(5, 5) == [(5, 5)]
    assert logic.block_ranges(0, 4500, 2000) == [(0, 1999), (2000, 3999), (4000, 4500)]


def test_span_from_limit_error() -> None:
    message = (
        "Under the Free tier plan, you can make eth_getLogs requests with up to a 10 block range."
    )
    assert logic.span_from_limit_error(message) == 10
    assert logic.span_from_limit_error("range limited to up to 2,000 block") == 2000
    assert logic.span_from_limit_error("unrelated failure") is None


def test_reverted_tx_with_failed_row_is_in_sync() -> None:
    row = make_row(status="failed")
    assert logic.compare_receipt(row, make_receipt(status=0, logs=[]), TOKEN) == []


def test_log_for_unconfirmed_row_is_flagged() -> None:
    log = logic.parse_transfer_log(make_log())
    for status in ("pending", "failed"):
        orphans = logic.find_orphans([make_row(status=status)], [log])
        assert orphans == [(log, f"DB row status={status} but chain has Transfer")]


def test_log_with_wrong_row_kind_is_flagged() -> None:
    log = logic.parse_transfer_log(make_log(sender=logic.ZERO_ADDRESS))
    row = make_row(from_addr=logic.ZERO_ADDRESS)  # kind=transfer, but the log is a mint
    assert logic.find_orphans([row], [log]) == [(log, "DB row kind=transfer differs from log")]
