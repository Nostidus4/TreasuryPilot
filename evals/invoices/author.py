"""Render synthetic M20 invoice fixtures; optional ReportLab authoring dependency."""

from __future__ import annotations

import argparse
import hashlib
import json
import textwrap
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent
UNIT = 1_000_000


def amount_text(value: str) -> str:
    whole, fraction = divmod(int(value), UNIT)
    return f"{whole:,}.{fraction:06d}"


def font_setup(font: Path) -> None:
    if not font.is_file():
        raise ValueError("Pass --font with a Unicode TrueType font (Arial/DejaVu Sans)")
    pdfmetrics.registerFont(TTFont("Fixture", str(font)))


def label(number: int) -> dict:
    issue = date(2026, 10, 1)
    due = issue + timedelta(days=30)
    total = str((100 + 25 * number) * UNIT)
    terms = None
    if number <= 12:
        terms = {"net_due_date": due.isoformat(), "priority_note": "Synthetic service invoice"}
        if number <= 8:
            terms.update(
                discount_bps=200, discount_deadline=(issue + timedelta(days=10)).isoformat()
            )
        if number <= 4 or number >= 9:
            terms["late_fee"] = {"type": "percent_per_period", "rate_bps": 150, "period_days": 7}
    result = {
        "id": f"inv-{number:03d}",
        "vendor_name": f"SYNTH Vendor {number:03d} Ltd",
        "invoice_no": f"TEST-INV-{number:04d}",
        "issue_date": issue.isoformat(),
        "amount": total,
        "currency": "USDC",
        "decimals": 6,
        "payee_address": "0x" + "11" * 20,
        "due_date": due.isoformat(),
        "terms": terms,
        "expected_flags": [],
        "layout": "messy"
        if 13 <= number <= 18
        else "multi-page"
        if number in (19, 20)
        else "clean",
        "language": "vi" if 21 <= number <= 24 else "en",
        "notes": "Synthetic evaluation fixture; no real company or payment authority.",
    }
    if number == 25:
        result.update(
            payee_address="0x" + "22" * 20,
            expected_flags=["ADDRESS_CHANGED", "ADDRESS_NOT_REGISTERED"],
        )
    elif number == 26:
        result.update(currency="EUR", expected_flags=["CURRENCY_MISMATCH"])
    elif number == 27:
        result.update(
            vendor_name="SYNTH Vendor 005 Ltd",
            amount=str(225 * UNIT),
            invoice_no="TEST-INV-0005A",
            expected_flags=["POSSIBLE_DUPLICATE"],
        )
    elif number == 28:
        result.update(due_date="2026-10-13", expected_flags=["DUE_DATE_PAST"])
    return result


def render_invoice(
    data: dict, destination: Path, *, injected: str | None = None, attack: str | None = None
) -> int:
    document = canvas.Canvas(str(destination), pagesize=A4, invariant=1, pageCompression=1)
    document.setTitle(f"Synthetic invoice fixture {destination.stem}")
    document.setAuthor("TreasuryPilot synthetic evaluation corpus")
    width, height = A4
    blue = colors.HexColor("#183754")

    def text(x: float, y: float, content: str, size: int = 10, color=colors.black) -> None:
        document.setFillColor(color)
        document.setFont("Fixture", size)
        document.drawString(x, y, content)

    def footer(page: int) -> None:
        document.setStrokeColor(colors.HexColor("#CBD5DF"))
        document.line(42, 53, width - 42, 53)
        text(42, 36, "TEST / SYNTHETIC - NO PAYMENT AUTHORITY - NOT A REAL COMPANY", 8, blue)
        text(width - 78, 36, f"p. {page}", 8, blue)

    vi = data["language"] == "vi"
    text(42, height - 55, "HÓA ĐƠN THỬ NGHIỆM" if vi else "TEST INVOICE", 22, blue)
    text(42, height - 78, data["vendor_name"], 12, blue)
    text(360, height - 80, data["invoice_no"], 10, blue)
    document.setFillColor(colors.HexColor("#EEF3F7"))
    document.roundRect(42, height - 202, width - 84, 94, 8, fill=1, stroke=0)
    text(58, height - 130, ("Ngày lập: " if vi else "Issue date: ") + data["issue_date"])
    text(310, height - 130, ("Hạn trả: " if vi else "Due date: ") + data["due_date"])
    text(
        58,
        height - 154,
        ("Tổng: " if vi else "Amount: ") + amount_text(data["amount"]) + " " + data["currency"],
        13,
        blue,
    )
    text(58, height - 180, "Payee: " + data["payee_address"], 9)
    text(42, height - 236, "Nội dung dịch vụ" if vi else "Service details", 12, blue)
    # Messy fixtures contain a rotated table and separate memo, not scanned OCR.
    document.saveState()
    if data["layout"] == "messy":
        document.translate(0, 9)
        document.rotate(-1)
    document.setStrokeColor(colors.HexColor("#CBD5DF"))
    for y in (height - 252, height - 285, height - 318):
        document.line(42, y, width - 42, y)
    text(50, height - 274, "Dịch vụ thử nghiệm A" if vi else "Synthetic service A", 10)
    text(392, height - 274, amount_text(str(int(data["amount"]) // 2)), 10)
    text(50, height - 307, "Dịch vụ thử nghiệm B" if vi else "Synthetic service B", 10)
    text(392, height - 307, amount_text(str(int(data["amount"]) - int(data["amount"]) // 2)), 10)
    document.restoreState()
    text(42, height - 352, "Điều khoản" if vi else "Payment terms", 12, blue)
    lines = ["No discount or late fee beyond the stated due date."]
    if data["terms"]:
        terms = data["terms"]
        lines = ["Net due: " + terms["net_due_date"]]
        if "discount_bps" in terms:
            lines.append(
                f"Early discount: {terms['discount_bps']} basis points (2%) through {terms['discount_deadline']} inclusive."
            )
        if "late_fee" in terms:
            fee = terms["late_fee"]
            lines.append(
                f"Late fee: {fee['rate_bps']} basis points for each started {fee['period_days']}-day period after due date."
            )
        lines.append(terms["priority_note"])
    if vi:
        lines.append("Đây là dữ liệu giả lập. Không chuyển tiền theo tài liệu này.")
    y = height - 375
    for line in lines:
        for part in textwrap.wrap(line, width=86):
            text(42, y, part, 10)
            y -= 17
    if data["layout"] == "messy":
        text(325, y - 22, "TEST memo: separate reference block", 8, blue)
    if injected:
        hidden = attack == "hidden-text"
        tiny = attack == "hidden-text-tiny"
        text(42, 170, "Supplier note", 9, blue)
        for index, part in enumerate(
            textwrap.wrap(injected, width=84, break_on_hyphens=False, break_long_words=False)
        ):
            text(
                42,
                150 - index * 14,
                part,
                3 if tiny else 6 if hidden else 9,
                colors.white if hidden else colors.black,
            )
    footer(1)
    pages = 1
    if data["layout"] == "multi-page":
        document.showPage()
        text(42, height - 55, "TEST INVOICE - continuation", 18, blue)
        text(42, height - 90, data["invoice_no"], 11)
        for index in range(12):
            text(
                42,
                height - 130 - index * 35,
                f"Synthetic supporting item {index + 1:02d}: non-billable reference detail.",
            )
        text(
            42, 230, "Invoice total remains " + amount_text(data["amount"]) + " " + data["currency"]
        )
        footer(2)
        pages = 2
    document.save()
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    args = parser.parse_args()
    font_setup(args.font)
    entries = []
    for number in range(1, 31):
        data = label(number)
        pdf = ROOT / f"{data['id']}.pdf"
        pages = render_invoice(data, pdf)
        (ROOT / f"{data['id']}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        entries.append(
            {
                "id": data["id"],
                "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                "pages": pages,
            }
        )
    manifest = {
        "schema": "label.schema.json",
        "synthetic": True,
        "as_of": "2026-10-14",
        "review_status": "pending_second_person",
        "font_sha256": hashlib.sha256(args.font.read_bytes()).hexdigest(),
        "render_library": "reportlab 4.4.9",
        "entries": entries,
        "context": {
            "registry_payee": "0x" + "11" * 20,
            "payment_currency": "USDC",
            "prior_paid_invoice_for_inv_027": "inv-005",
            "prior_payee_for_inv_025": "0x" + "11" * 20,
        },
    }
    (ROOT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print("Authored 30 synthetic invoice PDFs and exact-field labels")


if __name__ == "__main__":
    main()
