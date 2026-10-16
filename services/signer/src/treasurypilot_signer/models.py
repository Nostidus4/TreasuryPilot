from __future__ import annotations

from typing import Any
from uuid import UUID

from eth_utils import to_checksum_address
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to: str
    data: str

    @field_validator("to")
    @classmethod
    def valid_address(cls, value: str) -> str:
        if len(value) != 42 or not value.startswith("0x"):
            raise ValueError("to must be a 20-byte hex address")
        try:
            bytes.fromhex(value[2:])
        except ValueError as error:
            raise ValueError("to must be a 20-byte hex address") from error
        return to_checksum_address(value)  # eth_account rejects a lowercase `to`

    @field_validator("data")
    @classmethod
    def valid_calldata(cls, value: str) -> str:
        if not value.startswith("0x") or len(value) < 10 or len(value) % 2:
            raise ValueError("data must be 0x-prefixed calldata")
        try:
            bytes.fromhex(value[2:])
        except ValueError as error:
            raise ValueError("data must be 0x-prefixed calldata") from error
        return value


class Fees(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_fee_per_gas: int = Field(alias="maxFeePerGas", ge=0)
    max_priority_fee_per_gas: int = Field(alias="maxPriorityFeePerGas", ge=0)
    fee_cap_wei: int = Field(alias="feeCapWei", ge=0)


class SignRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    treasury_id: UUID | None = Field(default=None, alias="treasuryId")
    plan: dict[str, Any]
    attestation: dict[str, Any]
    signature: str
    step_seq: int = Field(alias="stepSeq", ge=0)
    payload: Payload
    fees: Fees

    @field_validator("signature")
    @classmethod
    def valid_signature(cls, value: str) -> str:
        if not value.startswith("0x") or len(value) < 4 or len(value) % 2:
            raise ValueError("signature must be 0x-prefixed hex")
        try:
            bytes.fromhex(value[2:])
        except ValueError as error:
            raise ValueError("signature must be 0x-prefixed hex") from error
        return value

    @property
    def typed_data(self) -> dict[str, Any]:
        # Accept the documented {attestation: typedData, signature} shape and the
        # worker's persisted {attestation: {typedData, ...}, signature} shape.
        nested = self.attestation.get("typedData")
        return nested if isinstance(nested, dict) else self.attestation

    @property
    def resolved_treasury_id(self) -> str | None:
        value = self.treasury_id or self.plan.get("treasuryId") or self.plan.get("treasury_id")
        return str(value) if value is not None else None


class SignResponse(BaseModel):
    tx_hash: str = Field(alias="txHash")
    nonce: int
    sender: str = Field(alias="from")


class ErrorResponse(BaseModel):
    code: str
