"""Full-stack Playwright E2E support: prepare the stack and serve a small control API.

`setup` migrates the database, deploys the contracts to the running Anvil (reusing
`deploy-local.sh`) and seeds the TEST dataset. `ctl` serves a loopback-only HTTP API the browser
specs call for the few things a browser cannot do:

- POST /login-token {"email"}: mint a fresh single-use magic-link token (the API only stores hashes).
- POST /tick: run the worker's chain event indexer, transaction tracker and payee activation once,
  instead of running Celery beat (deterministic, and no Redis).
- POST /advance-time {"seconds"}: `evm_increaseTime` + `evm_mine` on Anvil. The API and worker
  project Cooling -> Active from the wall clock (`now()`), which has no test clock, so the stored
  chain-time `active_from` of Cooling payees is also translated into the wall-clock frame.

Anvil dev keys only. Refuses any chain id other than 31337.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.request
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

RPC_URL = os.environ.get("E2E_ANVIL_RPC_URL", "http://127.0.0.1:8545")
STATE_PATH = REPO_ROOT / "apps" / "web" / "e2e-stack" / ".state" / "stack.json"
CTL_PORT = int(os.environ.get("E2E_CTL_PORT", "8790"))


def database_url() -> str:
    if url := os.environ.get("DATABASE_URL"):
        return url
    if all(k in os.environ for k in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB")):
        user, password, db = (
            quote(os.environ["POSTGRES_USER"]),
            quote(os.environ["POSTGRES_PASSWORD"]),
            os.environ["POSTGRES_DB"],
        )
        return f"postgresql+asyncpg://{user}:{password}@127.0.0.1:5432/{db}"
    return "postgresql+asyncpg://treasurypilot:treasurypilot@127.0.0.1:5432/treasurypilot"


def rpc(method: str, params: list[object]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(RPC_URL, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RuntimeError(f"{method} failed: {payload['error']}")
    return payload["result"]


def wait_for_anvil() -> None:
    for _ in range(60):
        try:
            if int(rpc("eth_chainId", []), 16) == 31337:
                return
            raise SystemExit("RPC is not chain id 31337; refusing to run the E2E stack there")
        except OSError:
            time.sleep(1)
    raise SystemExit(f"Anvil did not answer on {RPC_URL}")


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=REPO_ROOT, check=True)


def setup() -> None:
    wait_for_anvil()
    os.environ["DATABASE_URL"] = database_url()
    run(["uv", "run", "--frozen", "alembic", "-c", "services/api/alembic.ini", "upgrade", "head"])
    import seed_local

    manifest_path = REPO_ROOT / "deployments" / "31337.json"
    if not seed_local.is_deployed(manifest_path, RPC_URL):
        run(["infra/scripts/deploy-local.sh"])
    asyncio.run(
        seed_local.main_async(
            argparse.Namespace(
                manifest=str(manifest_path),
                rpc_url=RPC_URL,
                api_rpc_url=RPC_URL,
                config_dir=str(REPO_ROOT / "deployments" / "local"),
                web_url="http://localhost:4179/auth/verify",
            )
        )
    )
    manifest = json.loads(manifest_path.read_text())
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(
            {
                "orgId": str(seed_local.sid("org")),
                "treasuryId": str(seed_local.sid("treasury")),
                "module": manifest["module"],
                "safeT": manifest["safeT"],
                "testToken": manifest["testToken"],
                "ownerAddress": manifest["demoOwner"],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"E2E stack ready; state in {STATE_PATH}")


async def mint_token(email: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO magic_links (id, email, token_hash, created_at, expires_at) "
                    "VALUES (:id, :email, :hash, :now, :exp)"
                ),
                {
                    "id": uuid.uuid4(),
                    "email": email,
                    "hash": hashlib.sha256(token.encode()).digest(),
                    "now": now,
                    "exp": now + timedelta(hours=1),
                },
            )
    finally:
        await engine.dispose()
    return token


def tick() -> dict[str, Any]:
    os.environ["DATABASE_URL"] = database_url()
    from treasurypilot_worker.tasks import (
        activate_due_payees_task,
        index_events_task,
        track_transactions_task,
    )

    return {
        "tracked": track_transactions_task(),
        "indexed": index_events_task(),
        "activated": activate_due_payees_task(),
    }


async def shift_cooling_payees(offset_seconds: int) -> int:
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            result = await connection.execute(
                text(
                    "UPDATE payees SET active_from = active_from - make_interval(secs => :s) "
                    "WHERE status = 'Cooling'"
                ),
                {"s": offset_seconds},
            )
            return int(getattr(result, "rowcount", 0) or 0)
    finally:
        await engine.dispose()


def advance_time(seconds: int) -> dict[str, Any]:
    if not 0 < seconds <= 7 * 86_400:
        raise ValueError("seconds must be between 1 and 604800")
    rpc("evm_increaseTime", [seconds])
    rpc("evm_mine", [])
    chain_now = int(rpc("eth_getBlockByNumber", ["latest", False])["timestamp"], 16)
    # How far chain time runs ahead of the wall clock the API and worker read.
    ahead = max(0, chain_now - int(time.time()))
    shifted = asyncio.run(shift_cooling_payees(ahead))
    return {"chainTime": chain_now, "chainAheadOfWallSeconds": ahead, "payeesShifted": shifted}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return

    def _reply(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        self._reply(200, {"status": "ok"}) if self.path == "/health" else self._reply(404, {})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            if self.path == "/login-token":
                self._reply(200, {"token": asyncio.run(mint_token(str(payload["email"])))})
            elif self.path == "/tick":
                self._reply(200, tick())
            elif self.path == "/advance-time":
                self._reply(200, advance_time(int(payload["seconds"])))
            else:
                self._reply(404, {})
        except Exception as error:
            self._reply(500, {"error": f"{type(error).__name__}: {error}"})


def serve() -> None:
    os.environ["DATABASE_URL"] = database_url()
    print(f"E2E control API on http://127.0.0.1:{CTL_PORT}", flush=True)
    HTTPServer(("127.0.0.1", CTL_PORT), Handler).serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "ctl"])
    args = parser.parse_args()
    setup() if args.command == "setup" else serve()


if __name__ == "__main__":
    main()
