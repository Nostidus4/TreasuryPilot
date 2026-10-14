from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from treasurypilot_core.money import BaseUnits, format_base_units

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ZERO_ADDRESS = "0x" + "0" * 40
_MAX_UINT128 = (1 << 128) - 1
_DAY = timedelta(days=1)


def _object_map(value: object) -> dict[str, object]:
    return cast(dict[str, object], value) if isinstance(value, dict) else {}


def _object_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [cast(dict[str, object], item) for item in value if isinstance(item, dict)]


def _string_set(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    return {item for item in value if isinstance(item, str)}


def _integer(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _is_sandbox(environment: str) -> bool:
    return environment.casefold() in {"local", "demo"}


def default_payee_cooling_seconds(environment: str) -> int:
    return 300 if _is_sandbox(environment) else 86_400


def default_min_supply(environment: str, asset_decimals: int) -> BaseUnits | None:
    """Sandbox default for ``minSupply``; elsewhere it must be configured explicitly."""
    return BaseUnits(500 * 10**asset_decimals) if _is_sandbox(environment) else None


def _camel_case(value: str) -> str:
    first, *rest = value.split("_")
    return first + "".join(word.capitalize() for word in rest)


class MandateModel(BaseModel):
    model_config = ConfigDict(alias_generator=_camel_case, populate_by_name=True, extra="forbid")


def _address(value: str) -> str:
    if not _ADDRESS.fullmatch(value):
        raise ValueError("address must be a 20-byte 0x-prefixed hex value")
    return value.lower()


class ActionLimits(MandateModel):
    per_request: BaseUnits
    daily: BaseUnits


class RefillPath(MandateModel):
    from_wallet: str = Field(alias="from")
    to_wallet: str = Field(alias="to")

    @field_validator("from_wallet", "to_wallet")
    @classmethod
    def valid_wallet_address(cls, value: str) -> str:
        return _address(value)


class WalletBuffer(MandateModel):
    wallet: str
    minimum: BaseUnits
    target: BaseUnits | None = None

    @field_validator("wallet")
    @classmethod
    def valid_wallet_address(cls, value: str) -> str:
        return _address(value)


class MandateAssetPolicy(MandateModel):
    asset_id: uuid.UUID
    limits: dict[str, ActionLimits]
    buffers: list[WalletBuffer]


class MandateConfig(MandateModel):
    actions: list[Literal["REFILL", "PAY", "SUPPLY", "SWAP"]] | None = None
    refill_paths: list[RefillPath] | None = None
    limits: dict[str, ActionLimits] | None = None
    buffers: list[WalletBuffer] | None = None
    asset_policies: list[MandateAssetPolicy] | None = None
    gas_funding_cap_wei: BaseUnits | None = None
    swap: dict[str, object] | None = None
    executor: str | None = None
    approvers: list[str] | None = None
    guardian: str | None = None
    valid_from: datetime | None = None
    expires_at: datetime | None = None
    payee_cooling_seconds: int | None = Field(default=None, ge=1)
    approval_max_age: int = Field(default=14 * 86_400, ge=1)
    supply_limits: ActionLimits | None = None
    min_supply: BaseUnits | None = None
    reserve_horizon_days: int = Field(default=30, ge=1, le=365)

    @field_validator("executor", "guardian")
    @classmethod
    def valid_contract_address(cls, value: str | None) -> str | None:
        return _address(value) if value is not None else None

    @field_validator("approvers")
    @classmethod
    def valid_approver_addresses(cls, values: list[str] | None) -> list[str] | None:
        return [_address(value) for value in values] if values is not None else None

    @field_validator("valid_from", "expires_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC) if value is not None else None

    def json_config(self, *, environment: str, asset_decimals: int) -> dict[str, object]:
        payload = self.model_dump(mode="json", by_alias=True, exclude_none=True)
        if self.payee_cooling_seconds is None:
            payload["payeeCoolingSeconds"] = default_payee_cooling_seconds(environment)
        min_supply = self.min_supply
        if min_supply is None:
            min_supply = default_min_supply(environment, asset_decimals)
        if min_supply is not None:
            payload["minSupply"] = str(int(min_supply))
        return payload


class MandateValidationError(Exception):
    def __init__(self, code: str, detail: str, *, fields: list[str] | None = None) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.fields = fields


def validate_mandate_config(
    config: MandateConfig,
    *,
    known_wallets: dict[str, str],
    environment: str,
    asset_decimals: int,
    now: datetime,
    enforce_future_expiry: bool = True,
    primary_asset_id: uuid.UUID | None = None,
    asset_metadata: dict[str, dict[str, object]] | None = None,
) -> None:
    required = (
        "actions",
        "refill_paths",
        "limits",
        "buffers",
        "gas_funding_cap_wei",
        "executor",
        "approvers",
        "guardian",
        "valid_from",
        "expires_at",
    )
    missing = [field for field in required if getattr(config, field) is None]
    if missing:
        public_names = [_camel_case(field) for field in missing]
        raise MandateValidationError(
            "MANDATE_INCOMPLETE",
            "The mandate draft is missing required fields.",
            fields=public_names,
        )

    assert config.actions is not None
    assert config.refill_paths is not None
    assert config.limits is not None
    assert config.buffers is not None
    assert config.gas_funding_cap_wei is not None
    assert config.executor is not None
    assert config.approvers is not None
    assert config.guardian is not None
    assert config.valid_from is not None
    assert config.expires_at is not None

    if not config.actions or len(set(config.actions)) != len(config.actions):
        raise MandateValidationError(
            "MANDATE_INCOMPLETE", "At least one unique action is required."
        )
    if "SWAP" in config.actions or config.swap is not None:
        raise MandateValidationError(
            "SWAP_UNAVAILABLE", "SWAP requires the optional router integration, which is disabled."
        )
    if not 0 <= asset_decimals <= 255:
        raise MandateValidationError(
            "ASSET_DECIMALS_OUT_OF_RANGE", "The treasury asset must use 0 to 255 decimals."
        )
    if config.executor == _ZERO_ADDRESS:
        raise MandateValidationError(
            "MANDATE_INCOMPLETE", "The executor cannot be the zero address."
        )
    if config.guardian == _ZERO_ADDRESS:
        raise MandateValidationError("MANDATE_INCOMPLETE", "A non-zero guardian is required.")
    if not config.approvers:
        raise MandateValidationError("NO_APPROVERS", "At least one approver is required.")
    if len(set(config.approvers)) != len(config.approvers):
        raise MandateValidationError("MANDATE_INCOMPLETE", "Approver addresses must be unique.")

    if config.valid_from >= config.expires_at:
        raise MandateValidationError("EXPIRY_BEFORE_START", "expiresAt must be after validFrom.")
    if enforce_future_expiry and config.expires_at <= now:
        raise MandateValidationError(
            "MANDATE_ALREADY_EXPIRED", "expiresAt must be in the future.", fields=["expiresAt"]
        )
    if config.expires_at - config.valid_from > _DAY * 365:
        raise MandateValidationError(
            "MANDATE_EXPIRY_TOO_LONG", "A mandate may be active for at most 365 days."
        )

    cooling = config.payee_cooling_seconds
    if cooling is None:
        cooling = default_payee_cooling_seconds(environment)
    min_cooling, max_cooling = (60, 3_600) if _is_sandbox(environment) else (3_600, 604_800)
    if not min_cooling <= cooling <= max_cooling:
        raise MandateValidationError(
            "COOLING_OUT_OF_RANGE",
            f"payeeCoolingSeconds must be between {min_cooling} and {max_cooling}.",
        )
    if not 86_400 <= config.approval_max_age <= 60 * 86_400:
        raise MandateValidationError(
            "APPROVAL_MAX_AGE_OUT_OF_RANGE", "approvalMaxAge must be between 1 and 60 days."
        )

    normalized_limits = config.limits
    if set(normalized_limits) - {"PAY", "REFILL"}:
        raise MandateValidationError(
            "MANDATE_INCOMPLETE", "Only PAY and REFILL limits are supported."
        )
    for action in config.actions:
        if action == "SUPPLY":
            if config.supply_limits is None:
                raise MandateValidationError(
                    "MANDATE_INCOMPLETE",
                    "A SUPPLY limit is required.",
                    fields=["supplyLimits"],
                )
        elif action not in normalized_limits:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", f"A {action} limit is required.", fields=[f"limits.{action}"]
            )
    limits_to_check = dict(normalized_limits)
    if config.supply_limits is not None:
        if "SUPPLY" not in config.actions:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", "supplyLimits requires the SUPPLY action."
            )
        limits_to_check["SUPPLY"] = config.supply_limits
    for limit_action, limits in limits_to_check.items():
        if limits.per_request > limits.daily:
            raise MandateValidationError(
                "PER_REQUEST_ABOVE_DAILY",
                f"The {limit_action} per-request limit exceeds its daily limit.",
            )
        if limits.per_request > _MAX_UINT128 or limits.daily > _MAX_UINT128:
            raise MandateValidationError(
                "AMOUNT_PRECISION",
                f"The {limit_action} amount exceeds the contract's uint128 range.",
            )
    min_supply = config.min_supply
    if min_supply is None:
        min_supply = default_min_supply(environment, asset_decimals)
    if min_supply is None and "SUPPLY" in config.actions:
        raise MandateValidationError(
            "MANDATE_INCOMPLETE",
            "minSupply must be configured for SUPPLY outside local and demo environments.",
            fields=["minSupply"],
        )
    if (
        config.gas_funding_cap_wei > _MAX_UINT128
        or (min_supply is not None and min_supply > _MAX_UINT128)
        or config.supply_limits is not None
        and (
            config.supply_limits.per_request > _MAX_UINT128
            or config.supply_limits.daily > _MAX_UINT128
        )
    ):
        raise MandateValidationError(
            "AMOUNT_PRECISION", "A configured amount exceeds uint128 range."
        )
    if (
        min_supply is not None
        and "SUPPLY" in config.actions
        and (
            min_supply == 0
            or config.supply_limits is not None
            and (
                min_supply > config.supply_limits.per_request
                or min_supply > config.supply_limits.daily
            )
        )
    ):
        raise MandateValidationError(
            "MIN_SUPPLY_ABOVE_LIMIT",
            "minSupply must be positive and no greater than either SUPPLY limit.",
            fields=["minSupply", "supplyLimits"],
        )

    if not known_wallets:
        raise MandateValidationError("UNKNOWN_WALLET", "The treasury has no verified Safe wallets.")
    buffers_by_wallet: dict[str, WalletBuffer] = {}
    for wallet_buffer in config.buffers:
        if wallet_buffer.wallet not in known_wallets:
            raise MandateValidationError(
                "UNKNOWN_WALLET", f"Unknown wallet: {wallet_buffer.wallet}."
            )
        if wallet_buffer.wallet in buffers_by_wallet:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", "Each wallet may have one buffer entry."
            )
        role = known_wallets[wallet_buffer.wallet]
        if role == "OPERATIONAL" and wallet_buffer.target is None:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE",
                "Operational wallet buffers require a target.",
                fields=[f"buffers.{wallet_buffer.wallet}.target"],
            )
        if (
            role == "OPERATIONAL"
            and wallet_buffer.target is not None
            and wallet_buffer.minimum > wallet_buffer.target
        ):
            raise MandateValidationError(
                "TARGET_BELOW_BUFFER", f"Target for {wallet_buffer.wallet} is below its buffer."
            )
        if wallet_buffer.minimum > _MAX_UINT128 or (
            wallet_buffer.target is not None and wallet_buffer.target > _MAX_UINT128
        ):
            raise MandateValidationError(
                "AMOUNT_PRECISION", "A wallet buffer exceeds uint128 range."
            )
        buffers_by_wallet[wallet_buffer.wallet] = wallet_buffer

    source_wallets = {address for address, role in known_wallets.items() if role == "SOURCE"}
    operational_wallets = {
        address for address, role in known_wallets.items() if role == "OPERATIONAL"
    }
    if not source_wallets.issubset(buffers_by_wallet):
        raise MandateValidationError(
            "MANDATE_INCOMPLETE", "A minimum Safe T buffer is required.", fields=["buffers.safeT"]
        )
    if not operational_wallets.issubset(buffers_by_wallet):
        raise MandateValidationError(
            "MANDATE_INCOMPLETE", "Every operational wallet requires a buffer and target."
        )
    seen_assets: set[uuid.UUID] = set()
    for policy in config.asset_policies or []:
        if policy.asset_id in seen_assets or policy.asset_id == primary_asset_id:
            raise MandateValidationError(
                "ASSET_POLICY_INVALID",
                "Each secondary payment asset must be unique and non-primary.",
            )
        seen_assets.add(policy.asset_id)
        metadata = (asset_metadata or {}).get(str(policy.asset_id))
        if asset_metadata is not None and (metadata is None or not metadata.get("address")):
            raise MandateValidationError(
                "ASSET_POLICY_INVALID", "A payment asset is not configured on this treasury chain."
            )
        if set(policy.limits) != {"PAY", "REFILL"}:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", "Each secondary asset requires PAY and REFILL limits."
            )
        for policy_action, limits in policy.limits.items():
            if limits.per_request > limits.daily:
                raise MandateValidationError(
                    "PER_REQUEST_ABOVE_DAILY",
                    f"The {policy_action} per-request limit exceeds its daily limit for asset {policy.asset_id}.",
                )
            if limits.per_request > _MAX_UINT128 or limits.daily > _MAX_UINT128:
                raise MandateValidationError(
                    "AMOUNT_PRECISION", f"An {action} limit exceeds uint128 range."
                )
        policy_buffers: dict[str, WalletBuffer] = {}
        for wallet_buffer in policy.buffers:
            if wallet_buffer.wallet not in known_wallets:
                raise MandateValidationError(
                    "UNKNOWN_WALLET", f"Unknown wallet for asset {policy.asset_id}."
                )
            if wallet_buffer.wallet in policy_buffers:
                raise MandateValidationError(
                    "MANDATE_INCOMPLETE", "Each asset requires one buffer entry per wallet."
                )
            role = known_wallets[wallet_buffer.wallet]
            if role == "OPERATIONAL":
                # Enabling an asset needs a positive refill target; Safe T has no target to compare.
                if not wallet_buffer.target:
                    raise MandateValidationError(
                        "MANDATE_INCOMPLETE", "Each operational asset buffer requires a target."
                    )
                if wallet_buffer.minimum > wallet_buffer.target:
                    raise MandateValidationError(
                        "TARGET_BELOW_BUFFER",
                        f"Asset target for {wallet_buffer.wallet} is below its buffer.",
                    )
            elif wallet_buffer.minimum == 0:
                raise MandateValidationError(
                    "MANDATE_INCOMPLETE", "Safe T requires a positive buffer for each asset."
                )
            if wallet_buffer.minimum > _MAX_UINT128 or (
                wallet_buffer.target is not None and wallet_buffer.target > _MAX_UINT128
            ):
                raise MandateValidationError(
                    "AMOUNT_PRECISION", "An asset wallet buffer exceeds uint128 range."
                )
            policy_buffers[wallet_buffer.wallet] = wallet_buffer
        if set(policy_buffers) != set(known_wallets):
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", "Every wallet requires an explicit buffer for each asset."
            )

    for path in config.refill_paths:
        if path.from_wallet not in known_wallets or path.to_wallet not in known_wallets:
            raise MandateValidationError(
                "UNKNOWN_WALLET", "A refill path references an unknown wallet."
            )
        if path.from_wallet not in source_wallets or path.to_wallet not in operational_wallets:
            raise MandateValidationError(
                "MANDATE_INCOMPLETE", "Refill paths must run from Safe T to an operational wallet."
            )


def build_summary(
    config: MandateConfig,
    *,
    decimals: int,
    symbol: str,
    asset_metadata: dict[str, dict[str, object]] | None = None,
) -> list[dict[str, str]]:
    summary: list[dict[str, str]] = []
    if config.actions:
        summary.append(
            {
                "field": "actions",
                "text": f"Enabled actions: {', '.join(config.actions)}.",
            }
        )
    if config.refill_paths:
        paths = sorted((path.from_wallet, path.to_wallet) for path in config.refill_paths)
        summary.append(
            {
                "field": "refillPaths",
                "text": "Refill paths: "
                + "; ".join(f"{source} → {target}" for source, target in paths)
                + ".",
            }
        )
    if config.limits:
        for action in sorted(config.limits):
            limits = config.limits[action]
            disabled_text = (
                " Action disabled because a limit is zero."
                if limits.per_request == 0 or limits.daily == 0
                else ""
            )
            summary.append(
                {
                    "field": f"limits.{action}",
                    "text": (
                        f"{action}: up to {format_base_units(limits.per_request, decimals)} {symbol} "
                        f"per request and {format_base_units(limits.daily, decimals)} {symbol} per UTC day "
                        f"({int(limits.per_request)} / {int(limits.daily)} base units)."
                        f"{disabled_text}"
                    ),
                    "perRequestBaseUnits": str(int(limits.per_request)),
                    "dailyBaseUnits": str(int(limits.daily)),
                }
            )
    for policy in config.asset_policies or []:
        metadata = (asset_metadata or {}).get(str(policy.asset_id))
        if metadata is None:
            raise MandateValidationError(
                "ASSET_POLICY_INVALID", "A payment asset is not configured on this treasury chain."
            )
        policy_symbol = str(metadata["symbol"])
        policy_decimals = int(cast(int, metadata["decimals"]))
        for action, limits in sorted(policy.limits.items()):
            summary.append(
                {
                    "field": f"assetPolicies.{policy.asset_id}.limits.{action}",
                    "text": (
                        f"{policy_symbol} {action}: up to "
                        f"{format_base_units(limits.per_request, policy_decimals)} {policy_symbol} "
                        f"per request and {format_base_units(limits.daily, policy_decimals)} "
                        f"{policy_symbol} per UTC day."
                    ),
                    "perRequestBaseUnits": str(int(limits.per_request)),
                    "dailyBaseUnits": str(int(limits.daily)),
                }
            )

    if config.gas_funding_cap_wei is not None:
        summary.append(
            {
                "field": "gasFundingCapWei",
                "text": (
                    "Gas funding is capped at "
                    f"{format_base_units(config.gas_funding_cap_wei, 18)} ETH "
                    f"({int(config.gas_funding_cap_wei)} wei)."
                ),
                "baseUnits": str(int(config.gas_funding_cap_wei)),
            }
        )
    if config.executor is not None:
        summary.append({"field": "executor", "text": f"Executor: {config.executor}."})
    if config.approvers is not None:
        summary.append(
            {
                "field": "approvers",
                "text": f"Approvers: {', '.join(sorted(config.approvers)) or 'none'}.",
            }
        )
    if config.guardian is not None:
        summary.append({"field": "guardian", "text": f"Guardian: {config.guardian}."})
    if config.valid_from is not None:
        summary.append(
            {"field": "validFrom", "text": f"Mandate starts at {config.valid_from.isoformat()}."}
        )
    if config.expires_at is not None:
        summary.append(
            {"field": "expiresAt", "text": f"Mandate expires at {config.expires_at.isoformat()}."}
        )
    if config.payee_cooling_seconds is not None:
        summary.append(
            {
                "field": "payeeCoolingSeconds",
                "text": f"New payees cool down for {config.payee_cooling_seconds} seconds.",
                "seconds": str(config.payee_cooling_seconds),
            }
        )
    summary.append(
        {
            "field": "approvalMaxAge",
            "text": (
                f"Approvals are valid for up to {config.approval_max_age} seconds "
                f"({config.approval_max_age / 86_400:g} days)."
            ),
            "seconds": str(config.approval_max_age),
        }
    )
    if config.supply_limits is not None:
        limits = config.supply_limits
        disabled_text = (
            " Action disabled because a limit is zero."
            if limits.per_request == 0 or limits.daily == 0
            else ""
        )
        summary.append(
            {
                "field": "supplyLimits",
                "text": (
                    f"SUPPLY: up to {format_base_units(limits.per_request, decimals)} {symbol} "
                    f"per request and {format_base_units(limits.daily, decimals)} {symbol} per UTC day "
                    f"({int(limits.per_request)} / {int(limits.daily)} base units)."
                    f"{disabled_text}"
                ),
                "perRequestBaseUnits": str(int(limits.per_request)),
                "dailyBaseUnits": str(int(limits.daily)),
            }
        )
    for buffer in sorted(config.buffers or [], key=lambda item: item.wallet):
        text = (
            f"{buffer.wallet}: keep at least {format_base_units(buffer.minimum, decimals)} {symbol} "
            f"({int(buffer.minimum)} base units)"
        )
        item = {
            "field": f"buffers.{buffer.wallet}",
            "text": text,
            "minimumBaseUnits": str(int(buffer.minimum)),
        }
        if buffer.target is not None:
            item["text"] += (
                f" and refill up to {format_base_units(buffer.target, decimals)} {symbol} "
                f"({int(buffer.target)} base units)"
            )
            item["targetBaseUnits"] = str(int(buffer.target))
        item["text"] += "."
        summary.append(item)
    if config.min_supply is not None:
        summary.append(
            {
                "field": "minSupply",
                "text": (
                    f"Minimum supply is {format_base_units(config.min_supply, decimals)} {symbol} "
                    f"({int(config.min_supply)} base units)."
                ),
                "baseUnits": str(int(config.min_supply)),
            }
        )
    if config.reserve_horizon_days is not None:
        summary.append(
            {
                "field": "reserveHorizonDays",
                "text": f"Keep a {config.reserve_horizon_days}-day reserve horizon.",
                "days": str(config.reserve_horizon_days),
            }
        )
    return summary


def _utc_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _numeric_risk(
    before: object,
    after: object,
    *,
    higher_is_looser: bool,
    missing_before: str = "changed",
    missing_after: str = "changed",
) -> str:
    if before is None:
        return missing_before if after is not None else "changed"
    if after is None:
        return missing_after
    before_int, after_int = _integer(before), _integer(after)
    if before_int is None or after_int is None:
        return "changed"
    increased = after_int > before_int
    return (
        ("looser" if increased else "stricter")
        if higher_is_looser
        else ("stricter" if increased else "looser")
    )


def build_diff(
    previous: dict[str, object] | None, current: dict[str, object]
) -> list[dict[str, object]]:
    if previous is None:
        return []
    diffs: list[dict[str, object]] = []

    def add(path: str, before: object, after: object, risk: str, *, critical: bool = False) -> None:
        # ``critical`` fields hand control to another address, so they always need
        # confirmation even though they are neither looser nor stricter.
        if before == after:
            return
        marker = {"looser": "▲", "stricter": "▼", "changed": "•"}[risk]
        diffs.append(
            {
                "path": path,
                "before": before,
                "after": after,
                "risk": risk,
                "marker": marker,
                "requiresConfirmation": critical or risk == "looser",
            }
        )

    old_actions, new_actions = (
        _string_set(previous.get("actions", [])),
        _string_set(current.get("actions", [])),
    )
    added_actions, removed_actions = new_actions - old_actions, old_actions - new_actions
    if added_actions:
        add("actions.added", sorted(old_actions), sorted(new_actions), "looser")
    if removed_actions:
        add("actions.removed", sorted(old_actions), sorted(new_actions), "stricter")

    old_paths = {
        (item.get("from"), item.get("to")) for item in _object_list(previous.get("refillPaths", []))
    }
    new_paths = {
        (item.get("from"), item.get("to")) for item in _object_list(current.get("refillPaths", []))
    }
    if old_paths != new_paths:
        add(
            "refillPaths",
            sorted((str(source), str(target)) for source, target in old_paths),
            sorted((str(source), str(target)) for source, target in new_paths),
            "looser" if new_paths - old_paths else "stricter",
        )

    old_limits = _object_map(previous.get("limits", {}))
    new_limits = _object_map(current.get("limits", {}))
    for action in sorted(set(old_limits) | set(new_limits)):
        old_action = _object_map(old_limits.get(action, {}))
        new_action = _object_map(new_limits.get(action, {}))
        for field in ("perRequest", "daily"):
            before, after = old_action.get(field), new_action.get(field)
            risk = _numeric_risk(
                before,
                after,
                higher_is_looser=True,
                missing_before="looser",
                missing_after="stricter",
            )
            add(f"limits.{action}.{field}", before, after, risk)

    old_supply, new_supply = (
        _object_map(previous.get("supplyLimits", {})),
        _object_map(current.get("supplyLimits", {})),
    )
    for field in ("perRequest", "daily"):
        before, after = old_supply.get(field), new_supply.get(field)
        risk = _numeric_risk(
            before,
            after,
            higher_is_looser=True,
            missing_before="looser",
            missing_after="stricter",
        )
        add(f"supplyLimits.{field}", before, after, risk)

    old_buffers = {item.get("wallet"): item for item in _object_list(previous.get("buffers", []))}
    new_buffers = {item.get("wallet"): item for item in _object_list(current.get("buffers", []))}
    wallets = {
        wallet for wallet in old_buffers.keys() | new_buffers.keys() if isinstance(wallet, str)
    }
    for wallet in sorted(wallets):
        old_buffer, new_buffer = old_buffers.get(wallet, {}), new_buffers.get(wallet, {})
        before, after = old_buffer.get("minimum"), new_buffer.get("minimum")
        risk = _numeric_risk(
            before,
            after,
            higher_is_looser=False,
            missing_before="stricter",
            missing_after="looser",
        )
        add(f"buffers.{wallet}.minimum", before, after, risk)
        before, after = old_buffer.get("target"), new_buffer.get("target")
        if before != after:
            # A new target newly permits refills up to it; dropping one removes them.
            risk = _numeric_risk(
                before,
                after,
                higher_is_looser=True,
                missing_before="looser",
                missing_after="stricter",
            )
            add(f"buffers.{wallet}.target", before, after, risk)

    for field, higher_is_looser in (
        ("payeeCoolingSeconds", False),
        ("approvalMaxAge", True),
        ("gasFundingCapWei", True),
        ("minSupply", False),
        ("reserveHorizonDays", False),
    ):
        before, after = previous.get(field), current.get(field)
        if before != after:
            risk = _numeric_risk(
                before,
                after,
                higher_is_looser=higher_is_looser,
                missing_before="stricter",
                missing_after="looser",
            )
            add(field, before, after, risk)

    for field, later_is_looser in (("validFrom", False), ("expiresAt", True)):
        before, after = previous.get(field), current.get(field)
        if before == after:
            continue
        before_time, after_time = _utc_datetime(before), _utc_datetime(after)
        if before_time is None or after_time is None:
            risk = "stricter" if before_time is None and after_time is not None else "changed"
        else:
            later = after_time > before_time
            risk = (
                ("looser" if later else "stricter")
                if later_is_looser
                else ("stricter" if later else "looser")
            )
        add(field, before, after, risk)

    old_policies = {
        str(item.get("assetId")): item for item in _object_list(previous.get("assetPolicies", []))
    }
    new_policies = {
        str(item.get("assetId")): item for item in _object_list(current.get("assetPolicies", []))
    }
    for asset_key in sorted(old_policies.keys() | new_policies.keys()):
        add(
            f"assetPolicies.{asset_key}",
            old_policies.get(asset_key),
            new_policies.get(asset_key),
            "changed",
            critical=True,
        )
    for field in ("executor", "guardian", "swap"):
        before, after = previous.get(field), current.get(field)
        add(field, before, after, "changed", critical=True)

    old_approvers = _string_set(previous.get("approvers", []))
    new_approvers = _string_set(current.get("approvers", []))
    if old_approvers != new_approvers:
        add(
            "approvers",
            sorted(old_approvers),
            sorted(new_approvers),
            "looser" if new_approvers - old_approvers else "stricter",
        )
    return diffs


def build_bundle_preview(
    previous: dict[str, object] | None,
    current: dict[str, object],
    *,
    asset_metadata: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    previous = previous or {}
    calls: list[dict[str, object]] = []
    governance_fields = (
        "actions",
        "refillPaths",
        "limits",
        "supplyLimits",
        "gasFundingCapWei",
        "swap",
        "executor",
        "guardian",
        "validFrom",
        "expiresAt",
        "payeeCoolingSeconds",
        "approvalMaxAge",
    )
    configures_mandate = any(
        previous.get(field) != current.get(field) for field in governance_fields
    )
    if configures_mandate:
        calls.append(
            {
                "method": "configureMandate",
                "arguments": {field: current.get(field) for field in governance_fields},
            }
        )
    old_approvers = _string_set(previous.get("approvers", []))
    new_approvers = _string_set(current.get("approvers", []))
    if old_approvers != new_approvers:
        calls.append(
            {
                "method": "setApprovers",
                "arguments": {
                    "add": sorted(new_approvers - old_approvers),
                    "remove": sorted(old_approvers - new_approvers),
                },
            }
        )
    old_buffers = {item.get("wallet"): item for item in _object_list(previous.get("buffers", []))}
    new_buffers = {item.get("wallet"): item for item in _object_list(current.get("buffers", []))}
    for wallet, item in new_buffers.items():
        if old_buffers.get(wallet) != item:
            calls.append({"method": "setBuffer", "arguments": item})
    for wallet in sorted(old_buffers.keys() - new_buffers.keys(), key=str):
        # A removed buffer is cleared on-chain; otherwise the old one stays in force.
        calls.append(
            {"method": "setBuffer", "arguments": {"wallet": wallet, "minimum": "0", "target": "0"}}
        )
    old_policies = {
        str(item.get("assetId")): item for item in _object_list(previous.get("assetPolicies", []))
    }
    new_policies = {
        str(item.get("assetId")): item for item in _object_list(current.get("assetPolicies", []))
    }
    metadata = asset_metadata or {}
    for asset_key, policy in new_policies.items():
        # configureMandate clears every secondary policy on-chain, so all must be re-enabled.
        if old_policies.get(asset_key) == policy and not configures_mandate:
            continue
        asset_address = metadata.get(asset_key, {}).get("address", asset_key)
        for item in _object_list(policy.get("buffers", [])):
            calls.append(
                {
                    "method": "setBuffer",
                    "arguments": {"asset": asset_address, **item},
                }
            )
        calls.append(
            {
                "method": "setAssetPolicy",
                "arguments": {
                    "asset": asset_address,
                    "enabled": True,
                    "limits": policy.get("limits", {}),
                },
            }
        )
    for asset_key in sorted(old_policies.keys() - new_policies.keys()):
        asset_address = metadata.get(asset_key, {}).get("address", asset_key)
        calls.append(
            {
                "method": "setAssetPolicy",
                "arguments": {"asset": asset_address, "enabled": False},
            }
        )
    treasury_settings = [
        {"field": field, "value": current.get(field)}
        for field in ("minSupply", "reserveHorizonDays")
        if previous.get(field) != current.get(field)
    ]
    return {
        "calls": calls,
        "operation": 1 if len(calls) > 1 else 0,
        "transport": "MultiSendCallOnly" if len(calls) > 1 else "direct",
        "treasurySettings": treasury_settings,
    }
