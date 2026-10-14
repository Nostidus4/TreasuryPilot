"""Shared plumbing: env config, sandbox-only schema, JSON-RPC and Foundry helpers."""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

SCHEMA = "sandbox"  # this tool never touches any other schema
DDL = (
    f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.test_tokens (
        chain_id int NOT NULL, address bytea NOT NULL, deploy_tx_hash bytea NOT NULL,
        deploy_block bigint NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
        PRIMARY KEY (chain_id, address))""",
    f"""CREATE TABLE IF NOT EXISTS {SCHEMA}.test_transfers (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(), chain_id int NOT NULL,
        token bytea NOT NULL, from_addr bytea NOT NULL, to_addr bytea NOT NULL,
        amount numeric(78,0) NOT NULL,
        kind text NOT NULL CHECK (kind IN ('mint','transfer')),
        status text NOT NULL CHECK (status IN ('pending','confirmed','failed')),
        tx_hash bytea UNIQUE CHECK (tx_hash IS NULL OR octet_length(tx_hash) = 32),
        block_number bigint, created_at timestamptz NOT NULL DEFAULT now(),
        updated_at timestamptz NOT NULL DEFAULT now())""",
)


def require_env(*names: str) -> str:
    """Return the first set variable among `names`; the message never echoes values."""
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    raise SystemExit(f"Set one of: {', '.join(names)}")


def make_engine() -> AsyncEngine:
    url = require_env("DATABASE_URL", "SUPABASE_DATABASE_URL")
    for plain in ("postgresql://", "postgres://"):
        if url.startswith(plain):
            url = "postgresql+asyncpg://" + url[len(plain) :]
    return create_async_engine(url)


async def ensure_schema(conn: AsyncConnection) -> None:
    for statement in DDL:
        await conn.execute(text(statement))


def to_bytes(hex_string: str) -> bytes:
    return bytes.fromhex(hex_string.removeprefix("0x"))


def to_hex(raw: bytes | memoryview) -> str:
    return "0x" + bytes(raw).hex()


def rpc(url: str, method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    headers = {"content-type": "application/json", "user-agent": "onchain-reconcile/1"}
    try:
        with urllib.request.urlopen(
            urllib.request.Request(url, body, headers), timeout=60
        ) as reply:
            payload = json.load(reply)
    except urllib.error.HTTPError as error:  # providers return limits as HTTP 400 JSON bodies
        try:
            payload = json.load(error)
        except ValueError:
            raise RuntimeError(f"RPC {method} failed: HTTP {error.code}") from None
    except urllib.error.URLError:
        raise RuntimeError(f"RPC {method} failed: network error") from None
    if "error" in payload:
        raise RuntimeError(f"RPC {method} failed: {payload['error'].get('message', 'error')}")
    return payload["result"]


def foundry(command: list[str], rpc_url: str, signer: bool = False) -> str:
    """Run forge/cast; RPC URL goes via env. With signer=True PRIVATE_KEY is passed to Foundry.

    Foundry has no env var for raw keys, so the key is visible in this process's argv for the
    call's duration. Use throwaway Anvil/testnet keys only. Failures never echo argv or output.
    """
    arguments = [*command, "--private-key", require_env("PRIVATE_KEY")] if signer else command
    environment = {**os.environ, "ETH_RPC_URL": rpc_url}
    try:
        result = subprocess.run(
            arguments, env=environment, capture_output=True, text=True, check=False
        )
    except OSError:
        raise SystemExit(f"Cannot run {command[0]}; install Foundry") from None
    if result.returncode:
        raise SystemExit(f"{command[0]} {command[1]} failed; check RPC, balance and key")
    return result.stdout.strip()
