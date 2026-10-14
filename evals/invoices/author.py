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


# Vietnamese cases printing amounts with VN separators (1.234,500000). inv-024 keeps the
# English style so extractors face both conventions inside the vi set. Labels always stay
# canonical integer base units; only the printed text differs.
VN_NUMBER_FORMAT = frozenset({"inv-021", "inv-022", "inv-023"})

# (issue date, net days) overrides. inv-001..005 and inv-007..010 are deliberately absent:
# the red-team corpus (evals/redteam, #179) reuses them and asserts their printed fields.
# inv-025..028 keep the baseline dates that their contextual flags are reasoned against.
DATE_VARIATION = {
    6: (date(2026, 9, 15), 45),
    11: (date(2026, 9, 28), 21),
    12: (date(2026, 10, 8), 14),
    13: (date(2026, 9, 18), 30),
    14: (date(2026, 9, 20), 30),
    15: (date(2026, 10, 5), 45),
    16: (date(2026, 9, 10), 40),
    17: (date(2026, 10, 12), 7),
    18: (date(2026, 10, 2), 28),
    19: (date(2026, 9, 25), 30),
    21: (date(2026, 9, 30), 30),
    22: (date(2026, 10, 12), 14),
    23: (date(2026, 9, 5), 45),
    24: (date(2026, 10, 13), 30),
    29: (date(2026, 9, 22), 25),
    30: (date(2026, 10, 14), 30),
}
# Larger vi totals so thousands separators are actually printed.
AMOUNT_OVERRIDE = {
    21: 1_234_500_000,
    22: 2_750_000_000,
    23: 1_875_250_000,
}


def amount_text(value: str, vn: bool = False) -> str:
    whole, fraction = divmod(int(value), UNIT)
    text = f"{whole:,}.{fraction:06d}"
    return text.translate(str.maketrans(",.", ".,")) if vn else text


def font_setup(font: Path) -> None:
    if not font.is_file():
        raise ValueError("Pass --font with a Unicode TrueType font (Arial/DejaVu Sans)")
    pdfmetrics.registerFont(TTFont("Fixture", str(font)))


def label(number: int) -> dict:
    issue, net_days = DATE_VARIATION.get(number, (date(2026, 10, 1), 30))
    due = issue + timedelta(days=net_days)
    total = str(AMOUNT_OVERRIDE.get(number, (100 + 25 * number) * UNIT))
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
    vn = vi and data["id"] in VN_NUMBER_FORMAT

    def money(value: str) -> str:
        return amount_text(value, vn)

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
        ("Tổng: " if vi else "Amount: ") + money(data["amount"]) + " " + data["currency"],
        13,
        blue,
    )
    text(58, height - 180, ("Người nhận: " if vi else "Payee: ") + data["payee_address"], 9)
    text(42, height - 236, "Nội dung dịch vụ" if vi else "Service details", 12, blue)
    # Messy fixtures contain a rotated table and reordered terms, not a claim of scanned OCR.
    document.saveState()
    if data["layout"] == "messy":
        document.translate(0, 9)
        document.rotate(-1)
    document.setStrokeColor(colors.HexColor("#CBD5DF"))
    for y in (height - 252, height - 285, height - 318):
        document.line(42, y, width - 42, y)
    text(50, height - 274, "Dịch vụ thử nghiệm A" if vi else "Synthetic service A", 10)
    text(392, height - 274, money(str(int(data["amount"]) // 2)), 10)
    text(50, height - 307, "Dịch vụ thử nghiệm B" if vi else "Synthetic service B", 10)
    text(392, height - 307, money(str(int(data["amount"]) - int(data["amount"]) // 2)), 10)
    document.restoreState()
    text(42, height - 352, "Điều khoản" if vi else "Payment terms", 12, blue)
    lines = [
        "Không có chiết khấu hoặc phí trễ hạn ngoài ngày đến hạn đã nêu."
        if vi
        else "No discount or late fee beyond the stated due date."
    ]
    if data["terms"]:
        terms = data["terms"]
        lines = [("Hạn thanh toán: " if vi else "Net due: ") + terms["net_due_date"]]
        if "discount_bps" in terms:
            bps, deadline = terms["discount_bps"], terms["discount_deadline"]
            lines.append(
                f"Chiết khấu sớm: {bps} điểm cơ bản (2%) đến hết ngày {deadline}."
                if vi
                else f"Early discount: {bps} basis points (2%) through {deadline} inclusive."
            )
        if "late_fee" in terms:
            fee = terms["late_fee"]
            lines.append(
                f"Phí trễ hạn: {fee['rate_bps']} điểm cơ bản cho mỗi kỳ {fee['period_days']} ngày đã bắt đầu sau ngày đến hạn."
                if vi
                else f"Late fee: {fee['rate_bps']} basis points for each started {fee['period_days']}-day period after due date."
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
        text(42, 170, "Untrusted supplier note (synthetic attack fixture)", 9, blue)
        for index, part in enumerate(textwrap.wrap(injected, width=84)):
            text(
                42,
                150 - index * 14,
                part,
                6 if hidden else 9,
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
        text(42, 230, "Invoice total remains " + money(data["amount"]) + " " + data["currency"])
        footer(2)
        pages = 2
    document.save()
    return pages


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", type=Path, default=Path("C:/Windows/Fonts/arial.ttf"))
    parser.add_argument(
        "--only",
        help="Comma-separated ids to re-render (e.g. inv-006,inv-011); other PDFs, labels and "
        "manifest entries are kept byte-for-byte. Rendered entries record their own font_sha256.",
    )
    args = parser.parse_args()
    font_setup(args.font)
    font_hash = hashlib.sha256(args.font.read_bytes()).hexdigest()
    manifest_path = ROOT / "manifest.json"
    previous = json.loads(manifest_path.read_text(encoding="utf-8")) if args.only else None
    only = set(args.only.split(",")) if args.only else None
    kept = {e["id"]: e for e in previous["entries"]} if previous else {}
    entries = []
    for number in range(1, 31):
        data = label(number)
        if only is not None and data["id"] not in only:
            entries.append(kept[data["id"]])
            continue
        pdf = ROOT / f"{data['id']}.pdf"
        pages = render_invoice(data, pdf)
        (ROOT / f"{data['id']}.json").write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        entry = {
            "id": data["id"],
            "pdf_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
            "pages": pages,
        }
        if previous and font_hash != previous["font_sha256"]:
            entry["font_sha256"] = font_hash
        entries.append(entry)
    manifest = {
        "schema": "label.schema.json",
        "synthetic": True,
        "as_of": "2026-10-14",
        "review_status": "pending_second_person",
        "font_sha256": previous["font_sha256"] if previous else font_hash,
        "render_library": "reportlab 4.4.9",
        "entries": entries,
        "context": previous["context"]
        if previous
        else {
            "registry_payee": "0x" + "11" * 20,
            "payment_currency": "USDC",
            "prior_paid_invoice_for_inv_027": "inv-005",
            "prior_payee_for_inv_025": "0x" + "11" * 20,
        },
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Authored {len(only) if only else 30} synthetic invoice PDFs and exact-field labels")


if __name__ == "__main__":
    main()
