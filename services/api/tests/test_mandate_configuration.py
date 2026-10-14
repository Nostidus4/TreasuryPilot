from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from treasurypilot_api.mandate.configuration import (
    MandateConfig,
    MandateValidationError,
    build_bundle_preview,
    build_diff,
    build_summary,
    validate_mandate_config,
)

SAFE_T = "0x" + "11" * 20
OPERATIONAL = "0x" + "22" * 20
NOW = datetime(2026, 10, 13, tzinfo=UTC)


def config_payload() -> dict[str, object]:
    return {
        "actions": ["PAY", "REFILL"],
        "refillPaths": [{"from": SAFE_T, "to": OPERATIONAL}],
        "limits": {
            "PAY": {"perRequest": "2000000000", "daily": "10000000000"},
            "REFILL": {"perRequest": "2500000000", "daily": "12000000000"},
        },
        "buffers": [
            {"wallet": SAFE_T, "minimum": "1000000000"},
            {"wallet": OPERATIONAL, "minimum": "10000000", "target": "150000000"},
        ],
        "gasFundingCapWei": "50000000000000000",
        "executor": "0x" + "33" * 20,
        "approvers": ["0x" + "44" * 20],
        "guardian": "0x" + "55" * 20,
        "validFrom": "2026-10-15T00:00:00Z",
        "expiresAt": "2026-11-15T00:00:00Z",
    }


def known_wallets() -> dict[str, str]:
    return {SAFE_T: "SOURCE", OPERATIONAL: "OPERATIONAL"}


def test_incomplete_mandate_returns_missing_fields() -> None:
    config = MandateConfig.model_validate({})

    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )

    assert error.value.code == "MANDATE_INCOMPLETE"
    assert error.value.fields == [
        "actions",
        "refillPaths",
        "limits",
        "buffers",
        "gasFundingCapWei",
        "executor",
        "approvers",
        "guardian",
        "validFrom",
        "expiresAt",
    ]


def test_valid_mandate_uses_base_units_and_formats_summary_exactly() -> None:
    config = MandateConfig.model_validate(config_payload())
    validate_mandate_config(
        config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
    )

    summary = build_summary(config, decimals=6, symbol="tUSDC")
    pay = next(item for item in summary if item["field"] == "limits.PAY")
    assert pay["perRequestBaseUnits"] == "2000000000"
    assert pay["dailyBaseUnits"] == "10000000000"
    assert "2,000.000000" not in pay["text"]
    assert "2000.000000 tUSDC" in pay["text"]


def test_target_below_buffer_is_rejected() -> None:
    body = config_payload()
    body["buffers"] = [
        {"wallet": SAFE_T, "minimum": "100"},
        {"wallet": OPERATIONAL, "minimum": "20", "target": "10"},
    ]
    config = MandateConfig.model_validate(body)

    with pytest.raises(MandateValidationError, match="below its buffer") as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )

    assert error.value.code == "TARGET_BELOW_BUFFER"


def test_per_request_limit_cannot_exceed_daily_limit() -> None:
    body = config_payload()
    body["limits"] = {
        "PAY": {"perRequest": "200", "daily": "100"},
        "REFILL": {"perRequest": "1", "daily": "10"},
    }
    config = MandateConfig.model_validate(body)

    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )

    assert error.value.code == "PER_REQUEST_ABOVE_DAILY"


def test_supply_action_requires_separate_supply_limits() -> None:
    body = config_payload()
    body["actions"] = ["PAY", "REFILL", "SUPPLY"]
    config = MandateConfig.model_validate(body)

    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )

    assert error.value.code == "MANDATE_INCOMPLETE"
    assert error.value.fields == ["supplyLimits"]


def test_supply_limits_and_demo_minimum_supply_use_asset_base_units() -> None:
    body = config_payload()
    body["actions"] = ["PAY", "REFILL", "SUPPLY"]
    body["supplyLimits"] = {"perRequest": "5000000000", "daily": "20000000000"}
    config = MandateConfig.model_validate(body)

    validate_mandate_config(
        config, known_wallets=known_wallets(), environment="demo", asset_decimals=6, now=NOW
    )
    persisted = config.json_config(environment="demo", asset_decimals=6)
    normalized = MandateConfig.model_validate(persisted)
    summary = build_summary(normalized, decimals=6, symbol="tUSDC")

    assert persisted["minSupply"] == "500000000"
    supply = next(item for item in summary if item["field"] == "supplyLimits")
    minimum = next(item for item in summary if item["field"] == "minSupply")
    assert supply["perRequestBaseUnits"] == "5000000000"
    assert supply["dailyBaseUnits"] == "20000000000"
    assert minimum["baseUnits"] == "500000000"
    assert "500.000000 tUSDC" in minimum["text"]


def test_minimum_supply_cannot_exceed_supply_limits() -> None:
    body = config_payload()
    body["actions"] = ["PAY", "REFILL", "SUPPLY"]
    body["supplyLimits"] = {"perRequest": "100000000", "daily": "20000000000"}
    body["minSupply"] = "500000000"
    config = MandateConfig.model_validate(body)

    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )

    assert error.value.code == "MIN_SUPPLY_ABOVE_LIMIT"
    assert error.value.fields == ["minSupply", "supplyLimits"]


def test_production_requires_explicit_minimum_supply_only_for_supply() -> None:
    validate_mandate_config(
        MandateConfig.model_validate(config_payload()),
        known_wallets=known_wallets(),
        environment="production",
        asset_decimals=6,
        now=NOW,
    )

    payload = config_payload()
    payload["actions"] = ["PAY", "REFILL", "SUPPLY"]
    payload["supplyLimits"] = {"perRequest": "1000000000", "daily": "5000000000"}
    config = MandateConfig.model_validate(payload)

    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config,
            known_wallets=known_wallets(),
            environment="production",
            asset_decimals=6,
            now=NOW,
        )

    assert error.value.code == "MANDATE_INCOMPLETE"
    assert error.value.fields == ["minSupply"]


def test_unknown_wallet_and_missing_approver_are_rejected() -> None:
    body = config_payload()
    body["approvers"] = []
    config = MandateConfig.model_validate(body)
    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )
    assert error.value.code == "NO_APPROVERS"

    body = config_payload()
    body["buffers"] = [{"wallet": "0x" + "66" * 20, "minimum": "1"}]
    config = MandateConfig.model_validate(body)
    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )
    assert error.value.code == "UNKNOWN_WALLET"


def test_prod_ranges_and_mandate_expiry_are_enforced() -> None:
    body = config_payload()
    body["payeeCoolingSeconds"] = 300
    config = MandateConfig.model_validate(body)
    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config,
            known_wallets=known_wallets(),
            environment="production",
            asset_decimals=6,
            now=NOW,
        )
    assert error.value.code == "COOLING_OUT_OF_RANGE"

    body = config_payload()
    body["expiresAt"] = (datetime(2027, 10, 16, tzinfo=UTC)).isoformat()
    config = MandateConfig.model_validate(body)
    with pytest.raises(MandateValidationError) as error:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=6, now=NOW
        )
    assert error.value.code == "MANDATE_EXPIRY_TOO_LONG"


def test_float_amounts_and_naive_timestamps_are_rejected_at_input() -> None:
    body = config_payload()
    body["limits"] = {
        "PAY": {"perRequest": 1.25, "daily": "100"},
        "REFILL": {"perRequest": "1", "daily": "10"},
    }
    with pytest.raises(ValidationError):
        MandateConfig.model_validate(body)

    body = config_payload()
    body["validFrom"] = "2026-10-15T00:00:00"
    with pytest.raises(ValidationError, match="include a timezone"):
        MandateConfig.model_validate(body)


def test_looser_changes_are_marked_and_require_confirmation() -> None:
    previous: dict[str, object] = {
        "limits": {"PAY": {"perRequest": "100", "daily": "1000"}},
        "buffers": [{"wallet": OPERATIONAL, "minimum": "100", "target": "500"}],
        "payeeCoolingSeconds": 300,
        "approvalMaxAge": 86_400,
        "expiresAt": "2026-11-01T00:00:00Z",
        "approvers": ["0x" + "44" * 20],
    }
    current = {
        "limits": {"PAY": {"perRequest": "200", "daily": "1000"}},
        "buffers": [{"wallet": OPERATIONAL, "minimum": "50", "target": "500"}],
        "payeeCoolingSeconds": 240,
        "approvalMaxAge": 172_800,
        "expiresAt": "2026-12-01T00:00:00Z",
        "approvers": ["0x" + "44" * 20, "0x" + "66" * 20],
    }

    diff = build_diff(previous, current)

    loosened = [item for item in diff if item["risk"] == "looser"]
    assert {item["path"] for item in loosened} == {
        "limits.PAY.perRequest",
        f"buffers.{OPERATIONAL}.minimum",
        "payeeCoolingSeconds",
        "approvalMaxAge",
        "expiresAt",
        "approvers",
    }
    assert all(item["marker"] == "▲" and item["requiresConfirmation"] for item in loosened)


def test_supply_and_timezone_aware_expiry_changes_are_marked_looser() -> None:
    diff = build_diff(
        {
            "supplyLimits": {"perRequest": "100", "daily": "500"},
            "expiresAt": "2026-11-01T00:00:00Z",
        },
        {
            "supplyLimits": {"perRequest": "200", "daily": "500"},
            "expiresAt": "2026-12-01T01:00:00+02:00",
        },
    )

    loosened = {item["path"] for item in diff if item["risk"] == "looser"}
    assert loosened == {"supplyLimits.perRequest", "expiresAt"}


def test_bundle_preview_uses_direct_call_or_multisend_by_call_count() -> None:
    config = MandateConfig.model_validate(config_payload()).json_config(
        environment="local", asset_decimals=6
    )
    preview = build_bundle_preview(None, config)

    assert preview["transport"] == "MultiSendCallOnly"
    assert preview["operation"] == 1
    assert [call["method"] for call in preview["calls"]] == [
        "configureMandate",
        "setApprovers",
        "setBuffer",
        "setBuffer",
    ]
    assert preview["treasurySettings"] == [
        {"field": "minSupply", "value": "500000000"},
        {"field": "reserveHorizonDays", "value": 30},
    ]

    assert build_bundle_preview(config, config) == {
        "calls": [],
        "operation": 0,
        "transport": "direct",
        "treasurySettings": [],
    }


def test_expired_mandate_and_bad_asset_decimals_are_validation_errors() -> None:
    config = MandateConfig.model_validate(config_payload())

    with pytest.raises(MandateValidationError) as expired:
        validate_mandate_config(
            config,
            known_wallets=known_wallets(),
            environment="local",
            asset_decimals=6,
            now=datetime(2026, 11, 15, tzinfo=UTC),
        )
    assert expired.value.code == "MANDATE_ALREADY_EXPIRED"

    with pytest.raises(MandateValidationError) as decimals:
        validate_mandate_config(
            config, known_wallets=known_wallets(), environment="local", asset_decimals=256, now=NOW
        )
    assert decimals.value.code == "ASSET_DECIMALS_OUT_OF_RANGE"


def test_control_changes_and_new_buffer_targets_require_confirmation() -> None:
    previous = MandateConfig.model_validate(config_payload()).json_config(
        environment="local", asset_decimals=6
    )
    changed = dict(previous)
    changed["executor"] = "0x" + "66" * 20
    changed["guardian"] = "0x" + "77" * 20
    changed["buffers"] = [{"wallet": OPERATIONAL, "minimum": "10000000", "target": "150000000"}]
    previous_without_target = dict(previous)
    previous_without_target["buffers"] = [
        {"wallet": SAFE_T, "minimum": "1000000000"},
        {"wallet": OPERATIONAL, "minimum": "10000000"},
    ]

    control = {item["path"]: item for item in build_diff(previous, changed)}
    assert control["executor"]["requiresConfirmation"] is True
    assert control["guardian"]["requiresConfirmation"] is True

    added_target = {item["path"]: item for item in build_diff(previous_without_target, previous)}[
        f"buffers.{OPERATIONAL}.target"
    ]
    assert added_target["risk"] == "looser"
    assert added_target["requiresConfirmation"] is True

    calls = build_bundle_preview(previous, changed)["calls"]
    assert {
        "method": "setBuffer",
        "arguments": {"wallet": SAFE_T, "minimum": "0", "target": "0"},
    } in calls
