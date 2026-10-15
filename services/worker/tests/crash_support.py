"""Helpers for the RCV-007 crash suite: crash hooks, a signer stand-in and the child process.

Run as a script (``python crash_support.py '<json>'``) it executes one ``execute_step`` and dies
with ``os._exit`` at the requested point: a real process death (connection dropped mid-transaction,
no ``finally`` blocks), which the in-process ``Crash`` exception cannot reproduce.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request
import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import asyncpg  # type: ignore[import-untyped]
from eth_account import Account
from web3 import Web3

from treasurypilot_signer.store import SignerStore
from treasurypilot_worker.executor.outbox import StepExecution, execute_step
from treasurypilot_worker.locks import create_worker_pool

CHAIN_ID = 31337
SENDER = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"  # Anvil dev account 0
KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
EXIT_CODE = 77  # distinguishes a deliberate os._exit from any other child failure


class Crash(BaseException):
    """The worker process dies here (BaseException so no ``except Exception`` can swallow it)."""


class Hook:
    """Dies when the named boundary is reached: ``Crash`` in process, ``os._exit`` in a child."""

    def __init__(self, point: str | None, *, exit_process: bool = False) -> None:
        self.point, self.exit_process = point, exit_process

    def __call__(self, name: str) -> None:
        if name == self.point:
            if self.exit_process:
                os._exit(EXIT_CODE)
            raise Crash


class RpcError(Exception):
    pass


def rpc(url: str, method: str, params: Sequence[object] = ()) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    request = urllib.request.Request(url, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if "error" in payload:
        raise RpcError(str(payload["error"].get("message", "")).lower())
    return payload["result"]


@asynccontextmanager
async def signer_store(database_url: str) -> AsyncIterator[SignerStore]:
    async def use_signer_role(connection: asyncpg.Connection) -> None:
        await connection.execute("SET ROLE treasurypilot_signer")

    pool = await asyncpg.create_pool(
        database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        min_size=1,
        max_size=2,
        init=use_signer_role,
    )
    try:
        yield SignerStore(pool)
    finally:
        await pool.close()


class StoreSigner:
    """Signer stand-in with the real ``SigningService`` tail order on the real ``SignerStore``.

    reserve (nonce bound to attestation nonce + step id) -> sign and ``record_signed`` ->
    broadcast. A replay rebroadcasts the stored bytes and treats "already known" / "nonce too low"
    as success; a reservation without raw bytes is re-signed with the SAME reserved nonce.
    shortcut: attestation, mandate and fee checks are not run (they need a deployed module);
    upgrade when the module is wired into a suite.
    """

    def __init__(self, store: SignerStore, url: str, request_id: uuid.UUID, hook: Hook) -> None:
        self.store, self.url, self.hook, self.calls = store, url, hook, 0
        self.attestation_nonce = request_id.int
        self.plan_hash = bytes(Web3.keccak(request_id.bytes))

    async def sign_and_send(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        self.hook("before_signer")
        step_id = bytes.fromhex(request["plan"]["steps"][request["stepSeq"]]["stepId"][2:])
        payload = request["payload"]
        to, value = Web3.to_checksum_address(payload["to"]), int(payload["value"])
        pending = int(
            await asyncio.to_thread(rpc, self.url, "eth_getTransactionCount", [SENDER, "pending"]),
            16,
        )
        reserved = await self.store.reserve(
            attestation_nonce=self.attestation_nonce,
            plan_hash=self.plan_hash,
            step_id=step_id,
            payload_hash=bytes(Web3.keccak(bytes.fromhex(to[2:]) + value.to_bytes(32, "big"))),
            executor=bytes.fromhex(SENDER[2:]),
            pending_nonce=pending,
        )
        self.hook("after_reserve")
        if reserved.raw_transaction is not None:
            raw, tx_hash = bytes(reserved.raw_transaction), str(reserved.tx_hash)
        else:
            gas_price = int(await asyncio.to_thread(rpc, self.url, "eth_gasPrice"), 16)
            signed = Account.sign_transaction(
                {
                    "to": to,
                    "value": value,
                    "gas": 21000,
                    "gasPrice": gas_price,
                    "nonce": reserved.transaction_nonce,
                    "chainId": CHAIN_ID,
                },
                KEY,
            )
            raw, tx_hash = bytes(signed.raw_transaction), signed.hash.to_0x_hex()
            await self.store.record_signed(
                attestation_nonce=self.attestation_nonce,
                step_id=step_id,
                tx_hash=tx_hash,
                raw_transaction=raw,
            )
        self.hook("after_sign")
        try:
            await asyncio.to_thread(rpc, self.url, "eth_sendRawTransaction", ["0x" + raw.hex()])
        except RpcError as error:
            known = "already known" in str(error) or "known transaction" in str(error)
            if not (known or (reserved.replacement and "nonce too low" in str(error))):
                raise
        self.hook("after_broadcast")
        return {"txHash": tx_hash, "nonce": reserved.transaction_nonce, "from": SENDER}


class CrashConnection:
    def __init__(self, inner: Any, hook: Hook) -> None:
        self._inner, self._hook = inner, hook

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def execute(self, query: str, *args: Any) -> Any:
        if "SET status = 'Submitted'" in query:  # transactions row inserted, status not yet
            self._hook("mid_commit")
        return await self._inner.execute(query, *args)


class CrashPool:
    def __init__(self, inner: Any, hook: Hook) -> None:
        self._inner, self._hook = inner, hook

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[CrashConnection]:
        async with self._inner.acquire() as connection:
            yield CrashConnection(connection, self._hook)


async def _child(config: dict[str, Any]) -> None:
    step = StepExecution(
        treasury_id=uuid.UUID(config["treasury_id"]),
        request_id=uuid.UUID(config["request_id"]),
        plan_step_id=uuid.UUID(config["plan_step_id"]),
        step_id=bytes.fromhex(config["step_id"]),
        kind=config["kind"],
        chain_id=config["chain_id"],
        sign_request=config["sign_request"],
    )
    hook = Hook(config["point"], exit_process=True)
    pool = await create_worker_pool(config["database_url"], min_size=1, max_size=2)
    async with signer_store(config["database_url"]) as store:
        signer = StoreSigner(store, config["anvil_url"], step.request_id, hook)
        await execute_step(CrashPool(pool, hook), signer, step)  # type: ignore[arg-type]
        hook("after_submit_commit")
    sys.exit(3)  # the hook never fired: the test treats any other exit code as a failure


if __name__ == "__main__":
    asyncio.run(_child(json.loads(sys.argv[1])))
