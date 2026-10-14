from __future__ import annotations

import csv
import io
import time

import pytest

from treasurypilot_api.identity.auth import AuthFailure
from treasurypilot_api.invoices.requests import (
    CSV_MAX_ROWS,
    CSV_REQUIRED_COLUMNS,
    _csv_rows,
    _error_csv,
    _parse_csv_upload,
)


def test_csv_header_accepts_bom_and_ordered_optional_columns() -> None:
    content = (
        "\ufeffvendor_ref,payee_address,invoice_no,issue_date,due_date,amount,note,cost_center\n"
        "acme,0x" + "11" * 20 + ",INV-1,2026-10-01,2026-10-15,12.50,ok,FIN\n"
    ).encode()

    header, rows = _csv_rows(content)

    assert header == [*CSV_REQUIRED_COLUMNS, "note", "cost_center"]
    assert rows == [
        (
            2,
            {
                "vendor_ref": "acme",
                "payee_address": "0x" + "11" * 20,
                "invoice_no": "INV-1",
                "issue_date": "2026-10-01",
                "due_date": "2026-10-15",
                "amount": "12.50",
                "note": "ok",
                "cost_center": "FIN",
            },
        )
    ]


def test_csv_rejects_bad_headers_encoding_and_column_counts() -> None:
    with pytest.raises(AuthFailure) as header_error:
        _csv_rows(b"invoice_no,vendor_ref\nINV-1,acme\n")
    assert header_error.value.code == "CSV_HEADER_INVALID"

    with pytest.raises(AuthFailure) as encoding_error:
        _csv_rows(b"\xff\xfe")
    assert encoding_error.value.code == "CSV_ENCODING"

    header, rows = _csv_rows(
        (
            ",".join(CSV_REQUIRED_COLUMNS)
            + "\nacme,0x"
            + "11" * 20
            + ",INV-1,2026-10-01,2026-10-15\n"
        ).encode()
    )
    assert rows[0][1]["__csv_error__"] == "CSV_COLUMN_COUNT"


def test_multipart_csv_extracts_file_and_treasury_id() -> None:
    treasury_id = "00000000-0000-7000-8000-000000000040"
    boundary = "csv-import-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="treasuryId"\r\n\r\n{treasury_id}\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="invoices.csv"\r\n'
        "Content-Type: text/csv\r\n\r\nvendor_ref,invoice_no\r\nacme,INV-1\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    file_bytes, parsed_treasury_id = _parse_csv_upload(
        f"multipart/form-data; boundary={boundary}", body
    )

    assert file_bytes == b"vendor_ref,invoice_no\r\nacme,INV-1"
    assert str(parsed_treasury_id) == treasury_id


def test_error_csv_neutralizes_formula_cells_and_preserves_plain_values() -> None:
    errors = [
        {"row": 2, "field": "invoice_no", "code": "INVALID", "message": "bad", "value": "=1+1"},
        {"row": 3, "field": "note", "code": "INVALID", "message": "bad", "value": "+cmd"},
        {"row": 4, "field": "note", "code": "INVALID", "message": "bad", "value": "-cmd"},
        {"row": 5, "field": "note", "code": "INVALID", "message": "bad", "value": "@cmd"},
        {"row": 6, "field": "note", "code": "INVALID", "message": "bad", "value": "\tcmd"},
        {"row": 7, "field": "note", "code": "INVALID", "message": "bad", "value": "\rcmd"},
        {"row": 8, "field": "note", "code": "INVALID", "message": "bad", "value": "ordinary"},
    ]

    report = list(csv.reader(io.StringIO(_error_csv(errors).decode())))

    assert [row[-1] for row in report[1:]] == [
        "'=1+1",
        "'+cmd",
        "'-cmd",
        "'@cmd",
        "'\tcmd",
        "'\rcmd",
        "ordinary",
    ]


def test_parse_500_rows_within_import_performance_budget() -> None:
    header = ",".join(CSV_REQUIRED_COLUMNS)
    body = "\n".join(
        f"acme,0x{'11' * 20},INV-{index},2026-10-01,2026-10-15,12.50" for index in range(500)
    )
    started = time.perf_counter()

    parsed_header, rows = _csv_rows(f"{header}\n{body}\n".encode())

    elapsed = time.perf_counter() - started
    assert len(parsed_header) == len(CSV_REQUIRED_COLUMNS)
    assert len(rows) == 500
    assert elapsed < 10


def test_csv_row_limit_is_enforced() -> None:
    header = ",".join(CSV_REQUIRED_COLUMNS)
    row = f"acme,0x{'11' * 20},INV,2026-10-01,2026-10-15,12.50"

    with pytest.raises(AuthFailure) as error:
        _csv_rows((header + "\n" + (row + "\n") * (CSV_MAX_ROWS + 1)).encode())

    assert error.value.code == "CSV_ROW_LIMIT"


def test_csv_row_numbers_are_physical_lines_after_multiline_fields() -> None:
    header = ",".join(CSV_REQUIRED_COLUMNS) + ",note"
    prefix = f"acme,0x{'11' * 20},INV-{{n}},2026-10-01,2026-10-15,12.50"
    content = f'{header}\n{prefix.format(n=1)},"two\nlines"\n{prefix.format(n=2)},ok\n'

    _, rows = _csv_rows(content.encode())

    assert [number for number, _ in rows] == [2, 4]
