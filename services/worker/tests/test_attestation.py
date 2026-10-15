from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from eth_account import Account

from treasurypilot_core.policy import Decision
from treasurypilot_core.policy.attestation import verify_attestation
from treasurypilot_worker.attestation import (
    AttestationLogError,
    PolicyKeyUnavailable,
    attest,
    load_policy_key,
)

ROOT = Path(__file__).resolve().parents[3]
API_ROOT = ROOT / "services" / "api"
_PLAN = json.loads((ROOT / "contracts" / "test" / "vectors" / "plan-hash.json").read_text())[
    "plans"
][0]
PLAN: dict[str, Any] = {
    "requestId": _PLAN["requestId"],
    "treasury": _PLAN["treasury"],
    "chainId": _PLAN["chainId"],
    "steps": [
        {k: v for k, v in s.items() if k not in ("stepIdSource", "stepIdWallet")}
        for s in _PLAN["steps"]
    ],
}
POLICY_KEY = Account.from_key(bytes(31) + b"\x08")  # public fixture identity 8
PLAN_ID = UUID("01890000-0000-7000-8000-000000000001")
NOW = datetime(2027, 1, 15, 9, 0, tzinfo=UTC)
DECISION = Decision(
    decision="ALLOW",
    primary=None,
    codes=[],
    warnings=[],
    checks=[],
    stage="PLAN",
    step_seq=None,
    policy_version=bytes.fromhex("11" * 32),
    snapshot_block=7,
)


def _attest(database_url: str) -> tuple[dict[str, Any], bytes]:
    return attest(
        database_url,
        POLICY_KEY,
        plan_id=PLAN_ID,
        plan=PLAN,
        decision=DECISION,
        executor="0x22223333444455556666777788889999aaaabbbb",
        evidence_digest="0x" + "ee" * 32,
        now=NOW,
    )


def _keystore(tmp_path: Path, password: str) -> tuple[Path, Path]:
    keystore, password_file = tmp_path / "policy.json", tmp_path / "password"
    # Cheap KDF keeps the test fast; real keystores use the scrypt default.
    keystore.write_text(
        json.dumps(Account.encrypt(POLICY_KEY.key, password, kdf="pbkdf2", iterations=2))
    )
    password_file.write_text(password + "\n")
    return keystore, password_file


def test_the_policy_key_loads_from_an_encrypted_keystore(tmp_path: Path) -> None:
    keystore, password_file = _keystore(tmp_path, "correct horse")

    assert load_policy_key(keystore, password_file).address == POLICY_KEY.address


def test_a_wrong_password_or_missing_keystore_means_no_policy_key(tmp_path: Path) -> None:
    keystore, password_file = _keystore(tmp_path, "correct horse")
    password_file.write_text("wrong")

    with pytest.raises(PolicyKeyUnavailable):
        load_policy_key(keystore, password_file)
    with pytest.raises(PolicyKeyUnavailable):
        load_policy_key(tmp_path / "missing.json", password_file)
    with pytest.raises(PolicyKeyUnavailable):
        load_policy_key(None, None)


def test_no_signature_is_returned_when_the_row_cannot_be_written() -> None:
    with pytest.raises(AttestationLogError, match="attestations write failed"):
        _attest("postgresql://nobody:nothing@127.0.0.1:1/none")


@pytest.mark.integration
def test_the_attestation_row_is_stored_before_the_signature_is_returned() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is required for the attestations integration test")
    from alembic import command
    from alembic.config import Config

    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
    try:
        typed, signature = _attest(database_url)
        assert (
            verify_attestation(
                typed,
                signature,
                plan=PLAN,
                executor="0x22223333444455556666777788889999aaaabbbb",
                trusted_signers=[POLICY_KEY.address],
                now=NOW,
                bind_nonce=lambda nonce, plan_hash: plan_hash,
            )
            is None
        )
        asyncio.run(_verify_row(database_url, typed, signature))
    finally:
        command.downgrade(config, "base")


async def _verify_row(database_url: str, typed: dict[str, Any], signature: bytes) -> None:
    import asyncpg  # type: ignore[import-untyped]

    message = typed["message"]
    connection = await asyncpg.connect(database_url.replace("+asyncpg", "", 1))
    try:
        rows = await connection.fetch("SELECT * FROM attestations")
        assert len(rows) == 1
        row = rows[0]
        assert row["plan_id"] == PLAN_ID
        assert "0x" + row["plan_hash"].hex() == message["planHash"] == _PLAN["planHash"]
        assert ["0x" + s.hex() for s in row["step_ids"]] == message["stepIds"]
        assert int(row["nonce"]) == message["nonce"]
        assert int(row["valid_until"].timestamp()) == message["validUntil"]
        assert row["signature"] == signature
        assert row["policy_signer"] == POLICY_KEY.address
        assert json.loads(row["typed_data"]) == typed
        steps = await connection.fetch("SELECT * FROM plan_steps ORDER BY seq")
        assert len(steps) == len(PLAN["steps"])
        for saved, expected in zip(steps, PLAN["steps"], strict=True):
            assert saved["attestation_id"] == row["id"]
            assert saved["plan_id"] == PLAN_ID
            assert saved["seq"] == expected["seq"]
            assert "0x" + saved["step_id"].hex() == expected["stepId"]
            assert saved["action"] == expected["action"]
            assert "0x" + saved["request_id"].hex() == PLAN["requestId"]
            assert "0x" + saved["treasury_address"].hex() == PLAN["treasury"].lower()
            assert saved["chain_id"] == PLAN["chainId"]
            assert "0x" + saved["from_address"].hex() == expected["from"].lower()
            assert "0x" + saved["to_address"].hex() == expected["to"].lower()
            assert "0x" + saved["asset_address"].hex() == expected["asset"].lower()
            assert int(saved["amount"]) == int(expected["amount"])
        # Same nonce again: replay is refused by unique(nonce).
        with pytest.raises(asyncpg.UniqueViolationError):
            await connection.execute(
                "INSERT INTO attestations (id, plan_id, request_id, plan_hash, step_ids,"
                " policy_version, executor, nonce, valid_until, evidence_digest, typed_data,"
                " signature, policy_signer) SELECT gen_random_uuid(), plan_id, request_id,"
                " plan_hash, step_ids, policy_version, executor, nonce, valid_until,"
                " evidence_digest, typed_data, signature, policy_signer FROM attestations"
            )
        for statement in (
            "UPDATE attestations SET signature = '\\x00'",
            "DELETE FROM attestations",
            "UPDATE plan_steps SET amount = amount + 1",
            "DELETE FROM plan_steps",
        ):
            with pytest.raises(asyncpg.RaiseError, match="append-only"):
                await connection.execute(statement)
    finally:
        await connection.close()
