from __future__ import annotations

import csv
import io
import uuid
from datetime import date

import pytest

from treasurypilot_api.reconciliation.export import (
    ExportLine,
    ExportTotalsMismatch,
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


def _exp(*lines: ExportLine) -> dict[tuple[str, str], int]:
    out: dict[tuple[str, str], int] = {}
    for line in lines:
        key = (line.classification, line.asset)
        out[key] = out.get(key, 0) + line.amount
    return out


def _render(lines: list[ExportLine], fmt: str) -> str:
    return render(lines, fmt, _exp(*lines))


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def test_csv_amounts_are_exact_decimals_and_unmatched_status_included() -> None:
    rows = _rows(_render([_line()], "csv"))
    assert rows[1][5] == "1.234500"
    assert rows[1][8] == "0.000021000000000000"
    assert rows[1][9] == "Pending"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r", "\n"])
def test_formula_cells_are_neutralized(prefix: str) -> None:
    rows = _rows(_render([_line(vendor=prefix + "cmd")], "csv"))
    assert rows[1][2] == "'" + prefix + "cmd"


def test_journal_balances_per_line_with_generic_mapping() -> None:
    rows = _rows(_render([_line("FEE"), _line()], "journal"))[1:]
    assert [(r[3], r[5], r[6]) for r in rows[:2]] == [
        ("6100", "1.234500", "0"),
        ("1200", "0", "1.234500"),
    ]
    assert sum(float(r[5]) for r in rows) == sum(float(r[6]) for r in rows)


def test_totals_mismatch_aborts_with_differences() -> None:
    line = _line()
    with pytest.raises(ExportTotalsMismatch) as info:
        render([line], "csv", {("EXTERNAL_EXPENSE", "USDC"): line.amount + 1})
    assert info.value.diffs == [("EXTERNAL_EXPENSE", "USDC", line.amount + 1, line.amount)]


def test_missing_class_in_export_is_a_mismatch() -> None:
    with pytest.raises(ExportTotalsMismatch):
        render([], "csv", {("FEE", "ETH"): 5})


def test_totals_are_exact_past_28_digits() -> None:
    big = _line(amount=10**40 + 1)
    assert render([big], "csv", _exp(big))
    with pytest.raises(ExportTotalsMismatch):
        render([big], "csv", {("EXTERNAL_EXPENSE", "USDC"): 10**40})


def test_fee_column_blank_on_fee_lines_only() -> None:
    rows = _rows(_render([_line("FEE"), _line()], "csv"))
    assert rows[1][8] == "" and rows[2][8] != ""


def test_invoice_no_is_neutralized() -> None:
    line = _line()
    line = ExportLine(**{**line.__dict__, "invoice_no": "=HYPERLINK(1)"})
    assert _rows(_render([line], "csv"))[1][3] == "'=HYPERLINK(1)"


def test_journal_cells_are_neutralized() -> None:
    line = ExportLine(**{**_line().__dict__, "asset": "=SUM(A1)"})
    rows = _rows(_render([line], "journal"))
    assert all(r[7] == "'=SUM(A1)" for r in rows[1:])


def test_mapping_override_and_interest_lines_skip_totals_check() -> None:
    line = _line()
    interest = ExportLine(
        day=date(2026, 10, 31), request_id=None, vendor="", invoice_no="", classification="SUPPLY_INTEREST",
        amount=5, decimals=6, asset="USDC", tx_hash=b"", fee_wei=None, status="Computed", matched_by="",
    )  # fmt: skip
    mapping = {("EXTERNAL_EXPENSE", "CREDIT"): ("2000", "Bank")}
    rows = _rows(render([line], "journal", _exp(line), mapping, [interest]))[1:]
    assert [(r[2], r[3], r[5], r[6]) for r in rows] == [
        ("EXTERNAL_EXPENSE", "6000", "1.234500", "0"),
        ("EXTERNAL_EXPENSE", "2000", "0", "1.234500"),
        ("SUPPLY_INTEREST", "1300", "0.000005", "0"),
        ("SUPPLY_INTEREST", "4100", "0", "0.000005"),
    ]
    assert rows[2][8] == ""
