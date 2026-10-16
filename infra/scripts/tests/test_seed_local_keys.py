from __future__ import annotations

import sys
from pathlib import Path

import pytest
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


def test_upsert_env_handles_export_crlf_duplicates_and_comments(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_bytes(b"# A=old\r\n export A = 1\r\nA=2\r\nB=3\r\n")
    seed_local.upsert_env(env, {"A": "9", "C": '{"x":1}'})
    assert env.read_bytes() == b'# A=old\r\n export A = 1\r\nA=9\r\nB=3\r\nC={"x":1}\r\n'


def test_local_keystores_write_compact_json_and_readable_files(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("")
    seed_local.write_local_keystores(env, tmp_path / "keys")
    assert ", " not in env.read_text() and '": ' not in env.read_text()
    assert (tmp_path / "keys" / "executor.json").stat().st_mode & 0o777 == 0o644


def test_local_keystores_refuse_to_overwrite_foreign_wiring(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("TP_EXECUTOR_KEYSTORE_FILE=/etc/real/executor.json\n")
    with pytest.raises(SystemExit, match="TP_EXECUTOR_KEYSTORE_FILE"):
        seed_local.write_local_keystores(env, tmp_path / "keys")
    assert not (tmp_path / "keys").exists()
    seed_local.write_local_keystores(tmp_path / ".env2", tmp_path / "keys")  # fresh env is fine
    seed_local.write_local_keystores(tmp_path / ".env2", tmp_path / "keys")  # and idempotent


def test_local_keystores_accept_the_env_example_placeholders(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text((Path(__file__).parents[2] / "env" / ".env.example").read_text())
    seed_local.write_local_keystores(env, tmp_path / "keys")  # CI copies .env.example, then seeds
    assert seed_local._env_values(env)["TP_TRUSTED_POLICY_SIGNERS"].startswith('["0x')


@pytest.mark.parametrize(
    ("chain", "db"),
    [("0x1", "postgresql://x@localhost/db"), ("0x7a69", "postgresql://x@db.prod.example/db")],
)
def test_seed_refuses_non_local_targets(
    monkeypatch: pytest.MonkeyPatch, chain: str, db: str
) -> None:
    monkeypatch.setattr(seed_local, "rpc", lambda *_a: chain)
    with pytest.raises(SystemExit, match="refusing to seed"):
        seed_local.assert_local_targets("http://rpc", db)
    monkeypatch.setattr(seed_local, "rpc", lambda *_a: "0x7a69")
    seed_local.assert_local_targets("http://rpc", "postgresql://x@postgres/db")
