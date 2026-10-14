"""Outbox smoke: INSERT pending row (committed) -> broadcast -> UPDATE from the receipt.

Sends 1 mint and 3 transfers of the newest sandbox token on the RPC's chain.
Amounts are integer base units (TestUSDC has 6 decimals).
Env: RPC_URL, PRIVATE_KEY, DATABASE_URL or SUPABASE_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import json
import uuid

from sandbox_db import foundry, make_engine, require_env, rpc, to_bytes, to_hex
from sqlalchemy import text

ZERO = "0x" + "00" * 20
MINT_AMOUNT = 1_000_000_000
TRANSFER_AMOUNTS = (12_500_000, 250_000, 7_777_777)


def fresh_address(rpc_url: str) -> str:
    wallet = json.loads(foundry(["cast", "wallet", "new", "--json"], rpc_url))
    wallet = wallet.get("data", wallet) if isinstance(wallet, dict) else wallet
    wallet = wallet[0] if isinstance(wallet, list) else wallet
    return str(wallet["address"]).lower()  # the generated private key is discarded


async def main() -> None:
    rpc_url = require_env("RPC_URL")
    require_env("PRIVATE_KEY")
    chain_id = int(rpc(rpc_url, "eth_chainId", []), 16)
    deployer = foundry(["cast", "wallet", "address"], rpc_url, signer=True).lower()
    engine = make_engine()
    async with engine.connect() as conn:
        token_row = (
            await conn.execute(
                text(
                    "SELECT address FROM sandbox.test_tokens WHERE chain_id = :c"
                    " ORDER BY created_at DESC LIMIT 1"
                ),
                {"c": chain_id},
            )
        ).one_or_none()
    if token_row is None:
        raise SystemExit(f"No sandbox token for chain {chain_id}; run deploy_token.py first")
    token = to_hex(token_row.address)
    recipients = [fresh_address(rpc_url) for _ in TRANSFER_AMOUNTS]
    operations = [
        ("mint", ZERO, deployer, MINT_AMOUNT, ["mint(address,uint256)", deployer, str(MINT_AMOUNT)])
    ]
    for amount, to in zip(TRANSFER_AMOUNTS, recipients, strict=True):
        operations.append(
            ("transfer", deployer, to, amount, ["transfer(address,uint256)", to, str(amount)])
        )
    for kind, sender, to, amount, call in operations:
        row_id = uuid.uuid4()
        async with engine.begin() as conn:  # committed BEFORE broadcast
            await conn.execute(
                text(
                    "INSERT INTO sandbox.test_transfers"
                    "(id, chain_id, token, from_addr, to_addr, amount, kind, status)"
                    " VALUES (:i, :c, :t, :f, :to, :a, :k, 'pending')"
                ),
                {
                    "i": row_id,
                    "c": chain_id,
                    "t": to_bytes(token),
                    "f": to_bytes(sender),
                    "to": to_bytes(to),
                    "a": amount,
                    "k": kind,
                },
            )
        tx_hash = None
        try:
            sent = json.loads(
                foundry(["cast", "send", token, *call, "--json"], rpc_url, signer=True)
            )
            tx_hash = sent["transactionHash"]
            receipt = rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])
            status = "confirmed" if int(receipt["status"], 16) == 1 else "failed"
            block = int(receipt["blockNumber"], 16)
        except BaseException:  # never leave the committed pending row orphaned; keep any hash
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "UPDATE sandbox.test_transfers SET status = 'failed',"
                        " tx_hash = COALESCE(:h, tx_hash), updated_at = now() WHERE id = :i"
                    ),
                    {"h": to_bytes(tx_hash) if tx_hash else None, "i": row_id},
                )
            raise
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE sandbox.test_transfers SET tx_hash = :h, block_number = :n,"
                    " status = :s, updated_at = now() WHERE id = :i"
                ),
                {"h": to_bytes(tx_hash), "n": block, "s": status, "i": row_id},
            )
        print(f"{kind:8} {amount:>12} -> {to} tx={tx_hash} block={block} {status}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
