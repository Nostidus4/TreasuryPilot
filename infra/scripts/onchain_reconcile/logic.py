"""Pure reconciliation rules: compare DB rows with chain receipts and logs. No I/O."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
ZERO_ADDRESS = "0x" + "00" * 20
MAX_LOG_RANGE = 2000  # blocks per eth_getLogs request; free RPC tiers reject larger spans


@dataclass(frozen=True)
class Row:
    """A sandbox.test_transfers row with lowercase 0x-hex addresses and integer base units."""

    kind: str
    status: str
    tx_hash: str | None
    block_number: int | None
    from_addr: str
    to_addr: str
    amount: int


@dataclass(frozen=True)
class TransferLog:
    tx_hash: str
    log_index: int
    from_addr: str
    to_addr: str
    amount: int


def parse_transfer_log(log: dict[str, Any]) -> TransferLog:
    topics = log["topics"]
    return TransferLog(
        tx_hash=str(log["transactionHash"]).lower(),
        log_index=int(log["logIndex"], 16),
        from_addr="0x" + topics[1][-40:].lower(),
        to_addr="0x" + topics[2][-40:].lower(),
        amount=int(log["data"], 16),
    )


def is_transfer_log(log: dict[str, Any], token: str) -> bool:
    topics = log.get("topics") or []
    return (
        str(log["address"]).lower() == token.lower()
        and len(topics) == 3
        and topics[0].lower() == TRANSFER_TOPIC
    )


def expected_from(row: Row) -> str:
    return ZERO_ADDRESS if row.kind == "mint" else row.from_addr


def compare_receipt(row: Row, receipt: dict[str, Any] | None, token: str) -> list[str]:
    """DB -> chain: return human-readable problems (empty list means the row is in sync)."""
    if row.tx_hash is None:
        return [f"no tx_hash (status={row.status})"]
    if receipt is None:
        return ["receipt missing on chain"]
    problems: list[str] = []
    chain_status = "confirmed" if int(receipt["status"], 16) == 1 else "failed"
    if chain_status != row.status:
        problems.append(f"status db={row.status} chain={chain_status}")
    chain_block = int(receipt["blockNumber"], 16)
    if chain_block != row.block_number:
        problems.append(f"block db={row.block_number} chain={chain_block}")
    if str(receipt.get("to") or "").lower() != token.lower():
        problems.append("receipt.to is not the token")
    logs = [log for log in receipt.get("logs", []) if is_transfer_log(log, token)]
    if len(logs) != 1:
        problems.append(f"{len(logs)} Transfer logs (want 1)")
        return problems
    parsed = parse_transfer_log(logs[0])
    if parsed.from_addr != expected_from(row):
        problems.append(f"from db={expected_from(row)} chain={parsed.from_addr}")
    if parsed.to_addr != row.to_addr:
        problems.append(f"to db={row.to_addr} chain={parsed.to_addr}")
    if parsed.amount != row.amount:
        problems.append(f"amount db={row.amount} chain={parsed.amount}")
    return problems


def find_orphans(rows: list[Row], logs: list[TransferLog]) -> list[tuple[TransferLog, str]]:
    """Chain -> DB: on-chain Transfers with no matching row, or whose row disagrees."""
    known = {row.tx_hash.lower(): row for row in rows if row.tx_hash}
    orphans: list[tuple[TransferLog, str]] = []
    for log in logs:
        row = known.get(log.tx_hash)
        if row is None:
            orphans.append((log, "no DB row for tx"))
        elif (log.from_addr, log.to_addr, log.amount) != (
            expected_from(row),
            row.to_addr,
            row.amount,
        ):
            orphans.append((log, "DB row differs from log"))
    return orphans


def block_ranges(start: int, latest: int, span: int = MAX_LOG_RANGE) -> list[tuple[int, int]]:
    """Inclusive (from, to) chunks of at most `span` blocks covering start..latest."""
    ranges: list[tuple[int, int]] = []
    low = start
    while low <= latest:
        high = min(low + span - 1, latest)
        ranges.append((low, high))
        low = high + 1
    return ranges


def span_from_limit_error(message: str) -> int | None:
    """Parse "up to N block range" style provider errors into a usable span, if any."""
    match = re.search(r"up to (?:a )?([\d,]+) block", message, re.IGNORECASE)
    return int(match.group(1).replace(",", "")) if match else None
