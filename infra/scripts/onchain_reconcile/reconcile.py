"""Read-only reconciliation of sandbox.test_transfers against the chain. Exit 1 on mismatch.

Env: RPC_URL, DATABASE_URL or SUPABASE_DATABASE_URL.
Usage: uv run --frozen python infra/scripts/onchain_reconcile/reconcile.py
"""

from __future__ import annotations

import asyncio
import sys

from logic import (
    MAX_LOG_RANGE,
    TRANSFER_TOPIC,
    Row,
    TransferLog,
    compare_receipt,
    find_orphans,
    parse_transfer_log,
    span_from_limit_error,
)
from sandbox_db import make_engine, require_env, rpc, to_hex
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def load_rows(conn: AsyncConnection, chain_id: int, token: bytes) -> list[Row]:
    result = await conn.execute(
        text(
            "SELECT kind, status, tx_hash, block_number, from_addr, to_addr, amount"
            " FROM sandbox.test_transfers WHERE chain_id = :c AND token = :t ORDER BY created_at"
        ),
        {"c": chain_id, "t": token},
    )
    return [
        Row(
            kind=r.kind,
            status=r.status,
            tx_hash=to_hex(r.tx_hash) if r.tx_hash else None,
            block_number=r.block_number,
            from_addr=to_hex(r.from_addr),
            to_addr=to_hex(r.to_addr),
            amount=int(r.amount),
        )
        for r in result
    ]


def fetch_logs(rpc_url: str, token: str, start: int) -> list[TransferLog]:
    """All token Transfer logs since `start`, shrinking the span if the provider caps it."""
    latest = int(rpc(rpc_url, "eth_blockNumber", []), 16)
    logs: list[TransferLog] = []
    span = MAX_LOG_RANGE
    low = start
    while low <= latest:
        high = min(low + span - 1, latest)
        params = {
            "fromBlock": hex(low),
            "toBlock": hex(high),
            "address": token,
            "topics": [TRANSFER_TOPIC],
        }
        try:
            raw_logs = rpc(rpc_url, "eth_getLogs", [params])
        except RuntimeError as error:
            smaller = span_from_limit_error(str(error))
            if smaller is None or smaller >= span:
                raise
            span = smaller  # e.g. free-tier plans allow only 10 blocks per request
            continue
        logs.extend(parse_transfer_log(raw) for raw in raw_logs)
        low = high + 1
    return logs


async def main() -> int:
    rpc_url = require_env("RPC_URL")
    chain_id = int(rpc(rpc_url, "eth_chainId", []), 16)
    engine = make_engine()
    async with engine.connect() as conn:
        token_row = (
            await conn.execute(
                text(
                    "SELECT address, deploy_block FROM sandbox.test_tokens"
                    " WHERE chain_id = :c ORDER BY created_at DESC LIMIT 1"
                ),
                {"c": chain_id},
            )
        ).one()
        rows = await load_rows(conn, chain_id, bytes(token_row.address))
    await engine.dispose()
    token = to_hex(token_row.address)
    print(f"token={token} chain={chain_id} deploy_block={token_row.deploy_block}")
    mismatches = 0
    for row in rows:
        receipt = rpc(rpc_url, "eth_getTransactionReceipt", [row.tx_hash]) if row.tx_hash else None
        problems = compare_receipt(row, receipt, token)
        mismatches += bool(problems)
        verdict = "MISMATCH: " + "; ".join(problems) if problems else "OK"
        print(f"{row.tx_hash or '(none)'} {row.kind:8} {row.amount:>14} {verdict}")
    logs = fetch_logs(rpc_url, token, token_row.deploy_block)
    for log, reason in find_orphans(rows, logs):
        mismatches += 1
        print(f"{log.tx_hash} chain log {log.log_index} amount={log.amount} MISMATCH: {reason}")
    print(f"rows={len(rows)} chain_transfers={len(logs)} mismatches={mismatches}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
