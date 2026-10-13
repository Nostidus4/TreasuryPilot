"""Deterministic valuation of confirmed payment terms."""

from __future__ import annotations

from treasurypilot_core.domain import ApprovedRequest, LateFee, PaymentTerms
from treasurypilot_core.money import BaseUnits

_BASIS_POINTS_SCALE = 10_000
_DAYS_PER_YEAR = 365
_ZERO_BASE_UNITS = BaseUnits(0)


class InvalidTerms(ValueError):
    """A payment-terms value object is internally inconsistent.

    Normal input construction is guarded by Pydantic and therefore raises its
    ``ValidationError`` at the schema boundary. Engine entry points use this
    domain error as a defence against unchecked/deserialized model instances.
    """


def _invalid(message: str) -> InvalidTerms:
    return InvalidTerms(message)


def validate_terms(terms: PaymentTerms) -> None:
    """Validate terms at the engine boundary, raising :class:`InvalidTerms`."""

    if isinstance(terms.net_due_day, bool) or not isinstance(terms.net_due_day, int):
        raise _invalid("net_due_day must be an integer")
    if terms.net_due_day < 0:
        raise _invalid("net_due_day cannot be negative")
    if isinstance(terms.discount_bps, bool) or not isinstance(terms.discount_bps, int):
        raise _invalid("discount_bps must be an integer")
    if not 0 <= terms.discount_bps <= _BASIS_POINTS_SCALE:
        raise _invalid("discount_bps must be between 0 and 10000")

    deadline = terms.discount_deadline_day
    if terms.discount_bps > 0 and deadline is None:
        raise _invalid("discount_deadline_day is required when discount_bps is positive")
    if deadline is not None:
        if isinstance(deadline, bool) or not isinstance(deadline, int):
            raise _invalid("discount_deadline_day must be an integer")
        if deadline < 0:
            raise _invalid("discount_deadline_day cannot be negative")
        if terms.discount_bps == 0:
            raise _invalid("discount_bps must be positive when a discount deadline is set")
        if deadline > terms.net_due_day:
            raise _invalid("discount deadline cannot be after the net due day")

    if terms.late_fee is not None:
        _validate_late_fee(terms.late_fee)


def _validate_late_fee(late_fee: LateFee) -> None:
    if late_fee.kind == "fixed":
        if late_fee.amount is None:
            raise _invalid("a fixed late fee requires amount")
        if late_fee.rate_bps is not None or late_fee.period_days is not None:
            raise _invalid("a fixed late fee cannot define rate_bps or period_days")
    elif late_fee.kind == "percent_per_period":
        if late_fee.amount is not None:
            raise _invalid("a percent-per-period late fee cannot define amount")
        if late_fee.rate_bps is None or late_fee.period_days is None:
            raise _invalid("a percent-per-period late fee requires rate_bps and period_days")
        if isinstance(late_fee.rate_bps, bool) or not isinstance(late_fee.rate_bps, int):
            raise _invalid("late-fee rate_bps must be an integer")
        if not 0 <= late_fee.rate_bps <= _BASIS_POINTS_SCALE:
            raise _invalid("late-fee rate_bps must be between 0 and 10000")
        if isinstance(late_fee.period_days, bool) or not isinstance(late_fee.period_days, int):
            raise _invalid("late-fee period_days must be an integer")
        if late_fee.period_days <= 0:
            raise _invalid("late-fee period_days must be positive")
    else:
        raise _invalid(f"unsupported late-fee kind: {late_fee.kind}")

    if late_fee.cap is not None and not isinstance(late_fee.cap, BaseUnits):
        raise _invalid("late-fee cap must be BaseUnits")


def _validate_request_option(request: ApprovedRequest) -> None:
    early_amount = request.early_amount
    early_pay_by = request.early_pay_by
    if (early_amount is None) != (early_pay_by is None):
        raise _invalid("early_amount and early_pay_by must be defined together")
    if early_amount is None or early_pay_by is None:
        return
    if not isinstance(early_amount, BaseUnits):
        raise _invalid("early_amount must be BaseUnits")
    if early_amount == 0:
        raise _invalid("early_amount must be positive when an early option is present")
    if early_amount > request.amount:
        raise _invalid("early_amount cannot exceed the standard amount")
    if isinstance(early_pay_by, bool) or not isinstance(early_pay_by, int):
        raise _invalid("early_pay_by must be an integer")
    if early_pay_by < 0 or early_pay_by > request.terms.net_due_day:
        raise _invalid("early_pay_by must be on or before the net due day")


def _late_fee_amount(request: ApprovedRequest, pay_day: int) -> int:
    terms = request.terms
    late_fee = terms.late_fee
    if late_fee is None or pay_day <= terms.net_due_day:
        return 0

    if late_fee.kind == "fixed":
        assert late_fee.amount is not None  # validated at the engine boundary
        fee = int(late_fee.amount)
    else:
        assert late_fee.rate_bps is not None  # validated at the engine boundary
        assert late_fee.period_days is not None  # validated at the engine boundary
        late_days = pay_day - terms.net_due_day
        periods = (late_days + late_fee.period_days - 1) // late_fee.period_days
        fee = int(request.amount) * late_fee.rate_bps * periods // _BASIS_POINTS_SCALE

    if late_fee.cap is not None:
        return min(fee, int(late_fee.cap))
    return fee


def _early_payment(request: ApprovedRequest, pay_day: int) -> tuple[int, int] | None:
    """Return ``(pay_amount, exact_saving)`` when the early option is active."""

    if request.early_amount is not None and request.early_pay_by is not None:
        if pay_day <= request.early_pay_by:
            pay_amount = int(request.early_amount)
            return pay_amount, int(request.amount) - pay_amount
        return None

    # Legacy requests created before the two-option approval carry only the
    # confirmed bps terms. Retaining this path keeps the §8.2 golden examples
    # reproducible; new approvals should always persist the exact option.
    deadline = request.terms.discount_deadline_day
    if deadline is None or pay_day > deadline:
        return None
    saving = int(request.amount) * request.terms.discount_bps // _BASIS_POINTS_SCALE
    return int(request.amount) - saving, saving


def pay_amount(request: ApprovedRequest, pay_day: int) -> BaseUnits:
    """Return what paying ``request`` on ``pay_day`` debits: the early amount while
    an early option (exact or legacy ``discount_bps``) is active, else the standard amount.

    The scheduler, the liquidity reserve and the forecast share this so the debited
    amount always matches the one ``request_value`` credits.
    """

    early = _early_payment(request, pay_day)
    return request.amount if early is None else BaseUnits(early[0])


def request_value(
    request: ApprovedRequest,
    pay_day: int,
    *,
    fee_in_asset: BaseUnits = _ZERO_BASE_UNITS,
    supply_rate_bps: int = 0,
) -> int:
    """Return the integer value of paying ``request`` on ``pay_day``.

    For a two-option approval, saving is the exact standard amount minus the
    approved early amount. An active early option also bears the estimated plan
    fee and the simple supply interest forgone until the net due day. Late fees
    are assessed independently after the due day and capped when configured.
    """

    validate_terms(request.terms)
    _validate_request_option(request)
    if isinstance(pay_day, bool) or not isinstance(pay_day, int):
        raise TypeError("pay_day must be an integer")
    if pay_day < 0:
        raise InvalidTerms("pay_day cannot be negative")
    if not isinstance(fee_in_asset, BaseUnits):
        raise TypeError("fee_in_asset must be BaseUnits")
    if isinstance(supply_rate_bps, bool) or not isinstance(supply_rate_bps, int):
        raise TypeError("supply_rate_bps must be an integer")
    if supply_rate_bps < 0:
        raise InvalidTerms("supply_rate_bps cannot be negative")

    early = _early_payment(request, pay_day)
    early_value = 0
    if early is not None:
        pay_amount, saving = early
        days_earlier = max(request.terms.net_due_day - pay_day, 0)
        lost_supply_interest = (
            pay_amount * supply_rate_bps * days_earlier // (_BASIS_POINTS_SCALE * _DAYS_PER_YEAR)
        )
        early_value = saving - int(fee_in_asset) - lost_supply_interest

    return early_value - _late_fee_amount(request, pay_day)
