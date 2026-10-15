from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from treasurypilot_api.reconciliation.export import (
    ExportLine,
    ExportTotalsMismatch,
    _check_totals,
    render,
)


def _line(
    cls: str = "EXTERNAL_EXPENSE", vendor: str = "Acme", amount: int = 1_234_500
) -> ExportLine:
    return ExportLine(
        day=date(2026, 10, 1),
        request_id=uuid.UUID(int=1),
        vendor=vendor,
        invoice_no="INV-1",
        classification=cls,
        amount=amount,
        decimals=6,
        asset="USDC",
        tx_hash=b"\x11" * 32,
        fee_wei=21_000 * 10**9,
        status="Pending",
        matched_by="",
    )


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_csv_amounts_are_exact_decimals_and_unmatched_status_included() -> None:
    rows = _rows(render([_line()], "csv"))
    assert rows[1][5] == "1.234500"
    assert rows[1][8] == "0.000021000000000000"
    assert rows[1][9] == "Pending"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_formula_cells_are_neutralized(prefix: str) -> None:
    rows = _rows(render([_line(vendor=prefix + "cmd")], "csv"))
    assert rows[1][2] == "'" + prefix + "cmd"


def test_journal_balances_per_line_with_generic_mapping() -> None:
    rows = _rows(render([_line("FEE"), _line()], "journal"))[1:]
    assert [(r[3], r[5], r[6]) for r in rows[:2]] == [
        ("6100", "1.234500", "0"),
        ("1200", "0", "1.234500"),
    ]
    assert sum(float(r[5]) for r in rows) == sum(float(r[6]) for r in rows)


def test_totals_mismatch_aborts() -> None:
    line = _line()
    with pytest.raises(ExportTotalsMismatch):
        _check_totals([line], [(line, "1.234501")])
