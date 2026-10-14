"""Deploy contracts/src/test-assets/TestUSDC.sol with forge and record it in sandbox.test_tokens.

Needs contracts/node_modules (run `pnpm install` at the repo root) for OpenZeppelin.
Env: RPC_URL, PRIVATE_KEY, DATABASE_URL or SUPABASE_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from sandbox_db import (
    ensure_schema,
    foundry,
    make_engine,
    require_env,
    rpc,
    to_bytes,
)
from sqlalchemy import text

CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"


async def main() -> None:
    rpc_url = require_env("RPC_URL")
    require_env("PRIVATE_KEY")
    if not (CONTRACTS / "node_modules" / "@openzeppelin").exists():
        raise SystemExit("contracts/node_modules missing; run `pnpm install` at the repo root")
    chain_id = int(rpc(rpc_url, "eth_chainId", []), 16)
    out = json.loads(
        foundry(
            [
                "forge",
                "create",
                "src/test-assets/TestUSDC.sol:TestUSDC",
                "--root",
                str(CONTRACTS),
                "--broadcast",
                "--json",
            ],
            rpc_url,
            signer=True,
        )
    )
    token, tx_hash = out["deployedTo"], out["transactionHash"]
    block = int(rpc(rpc_url, "eth_getTransactionReceipt", [tx_hash])["blockNumber"], 16)
    engine = make_engine()
    async with engine.begin() as conn:
        await ensure_schema(conn)
        await conn.execute(
            text(
                "INSERT INTO sandbox.test_tokens(chain_id, address, deploy_tx_hash, deploy_block)"
                " VALUES (:c, :a, :t, :b) ON CONFLICT DO NOTHING"
            ),
            {"c": chain_id, "a": to_bytes(token), "t": to_bytes(tx_hash), "b": block},
        )
    await engine.dispose()
    print(f"chain_id={chain_id} token={token} deploy_tx={tx_hash} deploy_block={block}")


if __name__ == "__main__":
    asyncio.run(main())
