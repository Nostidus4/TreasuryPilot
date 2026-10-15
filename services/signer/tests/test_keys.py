from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from eth_account import Account
from fastapi.testclient import TestClient

from treasurypilot_signer.config import Settings
from treasurypilot_signer.keys import ExecutorKeyNotConfigured, ExecutorKeys, ExecutorKeyUnavailable
from treasurypilot_signer.main import create_app

PRIVATE_KEY = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
PASSWORD = "correct-horse"


def _settings(tmp_path: Path, *, password: str = PASSWORD, mapped: bool = True) -> Settings:
    keystore = tmp_path / "executor.json"
    keystore.write_text(
        json.dumps(Account.encrypt(bytes.fromhex(PRIVATE_KEY[2:]), PASSWORD, iterations=2))
    )
    password_file = tmp_path / "password"
    password_file.write_text(password)
    return Settings(
        executor_keystore_map={"treasury-1": str(keystore)} if mapped else {},
        executor_keystore_password_file=password_file,
    )


def test_validate_accepts_a_decryptable_keystore(tmp_path: Path) -> None:
    ExecutorKeys(_settings(tmp_path)).validate()


@pytest.mark.parametrize("kind", ["wrong-password", "no-keystore"])
def test_validate_refuses_bad_configuration(tmp_path: Path, kind: str) -> None:
    settings = (
        _settings(tmp_path, password="wrong", mapped=True)
        if kind == "wrong-password"
        else (_settings(tmp_path, mapped=False))
    )
    with pytest.raises(ExecutorKeyUnavailable):
        ExecutorKeys(settings).validate()


def test_service_does_not_start_with_a_wrong_password(tmp_path: Path) -> None:
    settings = _settings(tmp_path, password="wrong")
    settings.database_url = "postgresql://unused"
    settings.chain_rpc_url = "http://127.0.0.1:1"
    with pytest.raises(ExecutorKeyUnavailable), TestClient(create_app(settings_override=settings)):
        pass


def test_unmapped_treasury_is_not_configured(tmp_path: Path) -> None:
    with pytest.raises(ExecutorKeyNotConfigured):
        ExecutorKeys(_settings(tmp_path)).for_treasury("other")


def test_private_key_never_reaches_logs_or_health(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    settings = _settings(tmp_path, password="wrong")
    with pytest.raises(ExecutorKeyUnavailable):
        ExecutorKeys(settings).validate()
    keys = ExecutorKeys(_settings(tmp_path))
    keys.validate()
    with TestClient(create_app(settings_override=settings)) as client:
        health = client.get("/health").text

    secret = PRIVATE_KEY.removeprefix("0x")
    for text in (caplog.text, health):
        assert secret not in text.lower()
        assert PASSWORD not in text
