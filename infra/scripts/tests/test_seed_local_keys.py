from __future__ import annotations

import sys
from pathlib import Path

from eth_account import Account

sys.path.insert(0, str(Path(__file__).parents[1]))
import seed_local  # noqa: E402


def test_upsert_env_replaces_existing_keys_and_appends_missing_ones(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("A=1\nTP_EXECUTOR_ADDRESS=\nB=2\n")
    seed_local.upsert_env(env, {"TP_EXECUTOR_ADDRESS": "0xabc", "C": "3"})
    assert env.read_text() == "A=1\nTP_EXECUTOR_ADDRESS=0xabc\nB=2\nC=3\n"


def test_local_keystores_decrypt_to_the_public_anvil_keys_and_wire_the_env(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TP_SIGNER_SHARED_SECRET=keep-me\n")
    seed_local.write_local_keystores(env, tmp_path / "keys")
    values = dict(line.split("=", 1) for line in env.read_text().splitlines())
    password = (tmp_path / "keys" / "password").read_text()
    executor = Account.decrypt((tmp_path / "keys" / "executor.json").read_text(), password)
    assert Account.from_key(executor).address == values["TP_EXECUTOR_ADDRESS"]
    assert values["TP_EXECUTOR_ADDRESS"] == seed_local.ANVIL[1]  # the module's demo executor
    assert values["TP_SIGNER_SHARED_SECRET"] == "keep-me"
    assert values["TP_TRUSTED_POLICY_SIGNERS"].startswith('["0x')
