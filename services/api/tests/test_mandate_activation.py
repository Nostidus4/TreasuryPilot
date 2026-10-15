from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from eth_abi import decode
from eth_hash.auto import keccak
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from treasurypilot_api.mandate.activation import build_mandate_calls
from treasurypilot_api.mandate.configuration import build_bundle_preview
from treasurypilot_api.mandate.governance_service import GovernanceService
from treasurypilot_api.treasury.config import PlatformConfiguration

SAFE = "0x" + "11" * 20
OPERATIONAL = "0x" + "22" * 20
EXECUTOR = "0x" + "33" * 20
APPROVER = "0x" + "44" * 20
GUARDIAN = "0x" + "55" * 20
MODULE = bytes.fromhex("66" * 20)


def config() -> dict[str, object]:
    return {
        "actions": ["PAY", "REFILL", "SUPPLY"],
        "refillPaths": [{"from": SAFE, "to": OPERATIONAL}],
        "limits": {
            "PAY": {"perRequest": "200", "daily": "1000"},
            "REFILL": {"perRequest": "250", "daily": "1200"},
        },
        "supplyLimits": {"perRequest": "500", "daily": "2000"},
        "buffers": [
            {"wallet": SAFE, "minimum": "10"},
            {"wallet": OPERATIONAL, "minimum": "20", "target": "150"},
        ],
        "executor": EXECUTOR,
        "approvers": [APPROVER],
        "guardian": GUARDIAN,
        "validFrom": "2030-01-01T00:00:00Z",
        "expiresAt": "2030-02-01T00:00:00Z",
        "payeeCoolingSeconds": 300,
        "approvalMaxAge": 1200,
    }


def test_buffer_only_mandate_change_does_not_encode_configure_mandate() -> None:
    previous = config()
    current = config() | {
        "buffers": [
            {"wallet": SAFE, "minimum": "10"},
            {"wallet": OPERATIONAL, "minimum": "25", "target": "150"},
        ]
    }
    preview = build_bundle_preview(previous, current)

    encoded = build_mandate_calls(MODULE, cast(list[dict[str, object]], preview["calls"]))

    assert len(encoded) == 1
    assert encoded[0].to == MODULE
    assert encoded[0].data[:4] == keccak(b"setBuffer(address,uint256,uint256)")[:4]


def test_configure_mandate_encoding_includes_supply_limits() -> None:
    preview = build_bundle_preview(None, config())

    encoded = build_mandate_calls(MODULE, cast(list[dict[str, object]], preview["calls"]))
    selector = keccak(
        b"configureMandate((uint64,uint64,uint32,address,address,"
        b"(uint128,uint128),(uint128,uint128),uint32,(uint128,uint128)))"
    )[:4]
    argument = decode(
        [
            "(uint64,uint64,uint32,address,address,(uint128,uint128),"
            "(uint128,uint128),uint32,(uint128,uint128))"
        ],
        encoded[0].data[4:],
    )[0]

    assert encoded[0].data[:4] == selector
    assert argument[5] == (200, 1000)
    assert argument[6] == (250, 1200)
    assert argument[8] == (500, 2000)


def test_missing_guardian_encodes_as_the_zero_address() -> None:
    preview = build_bundle_preview(None, config() | {"guardian": None})

    encoded = build_mandate_calls(MODULE, cast(list[dict[str, object]], preview["calls"]))
    argument = decode(
        [
            "(uint64,uint64,uint32,address,address,(uint128,uint128),"
            "(uint128,uint128),uint32,(uint128,uint128))"
        ],
        encoded[0].data[4:],
    )[0]

    assert argument[4].lower() == "0x" + "00" * 20


def test_empty_mandate_diff_is_rejected() -> None:
    try:
        build_mandate_calls(MODULE, [])
    except ValueError as exc:
        assert "does not contain" in str(exc)
    else:
        raise AssertionError("empty mandate call list should fail")


def test_malformed_limits_and_oversized_values_raise_value_error() -> None:
    def call(**overrides: object) -> list[dict[str, object]]:
        return [{"method": "configureMandate", "arguments": config() | overrides}]

    assert build_mandate_calls(MODULE, call(limits=None))  # no AttributeError on null limits
    for overrides in (
        {"limits": "malformed"},
        {"payeeCoolingSeconds": 1 << 32},
        {"approvalMaxAge": 1.5},
        {"limits": {"PAY": {"perRequest": 1 << 128, "daily": "1"}}},
    ):
        with pytest.raises(ValueError):
            build_mandate_calls(MODULE, call(**overrides))


ORG = "00000000-0000-7000-8000-000000000010"
USER = "00000000-0000-7000-8000-000000000001"
TREASURY = "00000000-0000-7000-8000-000000000040"
MANDATE = "00000000-0000-7000-8000-000000000060"
GOVERNANCE_TX = uuid.UUID("00000000-0000-7000-8000-000000000070")
SEED_SQL = f"""
INSERT INTO users (id, email) VALUES ('{USER}', 'owner@example.com');
INSERT INTO organizations (id, name) VALUES ('{ORG}', 'Org A');
INSERT INTO chains (chain_id, name, is_testnet, confirmations, explorer_url, rpc_urls)
VALUES (11155111, 'Sepolia', true, 3, 'https://sepolia.etherscan.io', '["https://rpc"]');
INSERT INTO assets (id, chain_id, address, symbol, decimals, issuer_label) VALUES
    ('00000000-0000-7000-8000-000000000031', 11155111, decode(repeat('11', 20), 'hex'),
     'tUSDC', 6, 'Test');
INSERT INTO treasuries (id, org_id, chain_id, asset_id, module_address) VALUES
    ('{TREASURY}', '{ORG}', 11155111, '00000000-0000-7000-8000-000000000031',
     decode(repeat('66', 20), 'hex'))
"""


@pytest.mark.skipif(
    "TP_TEST_DATABASE_URL" not in os.environ,
    reason="TP_TEST_DATABASE_URL is required for PostgreSQL integration tests",
)
def test_activation_without_supply_limits_persists_pending_activation() -> None:
    api_root = Path(__file__).parents[1]
    database_url = os.environ["TP_TEST_DATABASE_URL"]
    alembic = Config(str(api_root / "alembic.ini"))
    alembic.set_main_option("script_location", str(api_root / "migrations"))
    alembic.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(alembic, "head")

    async def run() -> None:
        engine = create_async_engine(database_url)
        try:
            sessions = async_sessionmaker(engine)
            draft = config() | {"actions": ["PAY", "REFILL"]}
            draft.pop("supplyLimits")
            async with engine.begin() as connection:
                for statement in SEED_SQL.strip().split(";\n"):
                    await connection.execute(text(statement))
                await connection.execute(
                    text(
                        "INSERT INTO mandate_versions (id, org_id, treasury_id, version, config, "
                        "config_hash, valid_from, expires_at, created_by) VALUES "
                        f"('{MANDATE}', '{ORG}', '{TREASURY}', 1, CAST(:config AS jsonb), "
                        "decode(repeat('ab', 32), 'hex'), now(), now() + interval '30 days', "
                        f"'{USER}')"
                    ),
                    {"config": json.dumps(draft)},
                )
            service = GovernanceService(
                sessions,
                None,
                PlatformConfiguration(chains=(), manifests=()),
            )

            async def create(**_: object) -> dict[str, object]:
                async with engine.begin() as connection:
                    await connection.execute(
                        text(
                            "INSERT INTO governance_txs (id, org_id, treasury_id, chain_id, "
                            'safe_address, purpose, calls, "to", value, data, operation, '
                            "safe_nonce, safe_tx_hash, threshold, owners_snapshot, status) "
                            f"VALUES ('{GOVERNANCE_TX}', '{ORG}', '{TREASURY}', 11155111, "
                            "decode(repeat('22', 20), 'hex'), 'MANDATE', '[]', "
                            "decode(repeat('22', 20), 'hex'), 0, '\\x', 0, 1, "
                            "decode(repeat('ab', 32), 'hex'), 1, "
                            "ARRAY[decode(repeat('22', 20), 'hex')], 'Collecting')"
                        )
                    )
                return {"id": str(GOVERNANCE_TX)}

            service.create = create  # type: ignore[method-assign]
            result = await service.create_mandate_activation(
                organization_id=uuid.UUID(ORG),
                treasury_id=uuid.UUID(TREASURY),
                mandate_id=uuid.UUID(MANDATE),
                user_id=uuid.UUID(USER),
            )
            assert result["mandate"]["status"] == "PendingActivation"  # type: ignore[index]
            async with engine.connect() as connection:
                row = (
                    await connection.execute(
                        text(
                            "SELECT status, governance_tx_id FROM mandate_versions "
                            f"WHERE id = '{MANDATE}'"
                        )
                    )
                ).one()
                events = (
                    await connection.execute(
                        text(
                            "SELECT count(*) FROM mandate_status_events WHERE "
                            f"mandate_version_id = '{MANDATE}' AND to_status = 'PendingActivation'"
                        )
                    )
                ).scalar_one()
            assert (row.status, row.governance_tx_id, events) == (
                "PendingActivation",
                GOVERNANCE_TX,
                1,
            )
        finally:
            await engine.dispose()

    try:
        asyncio.run(run())
    finally:
        command.downgrade(alembic, "base")
