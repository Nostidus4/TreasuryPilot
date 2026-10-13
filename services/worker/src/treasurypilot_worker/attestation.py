"""Issue policy attestations in the core worker (POL-006): sign, persist, then hand out.

Only the `worker` (core) container mounts the policy keystore; `worker-ai` never sees it.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg  # type: ignore[import-untyped]
from eth_account import Account
from eth_account.signers.local import LocalAccount

from treasurypilot_core.ids import uuid7
from treasurypilot_core.policy import Decision
from treasurypilot_core.policy.attestation import attestation_typed_data, sign_attestation

DB_TIMEOUT_S = 5


class PolicyKeyUnavailable(RuntimeError):
    """The keystore or its password could not be read; no attestation can be issued."""


class AttestationLogError(RuntimeError):
    """The `attestations` row was not stored, so the signature is discarded (fail closed)."""


def load_policy_key(keystore: Path | None, password_file: Path | None) -> LocalAccount:
    if keystore is None or password_file is None:
        raise PolicyKeyUnavailable("policy keystore is not configured")
    try:
        key = Account.decrypt(keystore.read_text(), password_file.read_text().strip())
    except (OSError, ValueError) as error:
        # Never include the error text: it can echo keystore content.
        raise PolicyKeyUnavailable(f"policy keystore unreadable: {type(error).__name__}") from error
    account: LocalAccount = Account.from_key(key)
    return account


_INSERT = """
INSERT INTO attestations (
    id, plan_id, request_id, plan_hash, step_ids, policy_version, executor, nonce,
    valid_until, evidence_digest, typed_data, signature, policy_signer
) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13)
"""


def _b32(value: str) -> bytes:
    return bytes.fromhex(value.removeprefix("0x"))


def attest(
    database_url: str,
    policy_key: LocalAccount,
    *,
    plan_id: UUID,
    plan: Mapping[str, Any],
    decision: Decision,
    executor: str,
    evidence_digest: str,
    now: datetime,
    liquidity_cycle_id: str | None = None,
) -> tuple[dict[str, Any], bytes]:
    """Sign the PlanAttestation for an ALLOW@PLAN decision; return it only once its row is stored."""
    typed = attestation_typed_data(
        plan,
        decision,
        executor=executor,
        evidence_digest=evidence_digest,
        now=now,
        liquidity_cycle_id=liquidity_cycle_id,
    )
    signature = sign_attestation(typed, policy_key)
    try:
        asyncio.run(_insert(database_url, plan_id, typed, signature, policy_key.address))
    except Exception as error:
        raise AttestationLogError(f"attestations write failed: {type(error).__name__}") from error
    return typed, signature


async def _insert(
    database_url: str, plan_id: UUID, typed: dict[str, Any], signature: bytes, signer: str
) -> None:
    # shortcut: one connection per attestation (one per plan); pool it if plans get frequent.
    message = typed["message"]
    connection = await asyncpg.connect(
        database_url.replace("postgresql+asyncpg://", "postgresql://", 1),
        timeout=DB_TIMEOUT_S,
        command_timeout=DB_TIMEOUT_S,
    )
    try:
        await connection.execute(
            _INSERT,
            uuid7(),
            plan_id,
            _b32(message["requestId"]),
            _b32(message["planHash"]),
            [_b32(step_id) for step_id in message["stepIds"]],
            _b32(message["policyVersion"]),
            message["executor"],
            message["nonce"],
            datetime.fromtimestamp(message["validUntil"], UTC),
            _b32(message["evidenceDigest"]),
            json.dumps(typed),
            signature,
            signer,
        )
    finally:
        await connection.close()
