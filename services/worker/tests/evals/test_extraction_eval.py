"""The extraction eval runner end to end, on recordings built in the test (AGT-013)."""

import json
from pathlib import Path
from typing import Any

import pytest

from treasurypilot_worker.agent import (
    AiAdapter,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    load_ai_config,
)
from treasurypilot_worker.agent.prompts.extract import EXTRACT_TEMPLATE
from treasurypilot_worker.evals.extraction_eval import (
    REPO_ROOT,
    Case,
    RecordedProvider,
    RecordingError,
    load_cases,
    main,
    render_report,
    run_cases,
)
from treasurypilot_worker.evals.extraction_scoring import expected_terms, summarize

DATASET = REPO_ROOT / "evals" / "invoices"


def _located(value: str) -> dict[str, Any]:
    return {"value": value, "page": 1, "span": value}


def _perfect_answer(label: dict[str, Any]) -> dict[str, Any]:
    terms = None
    wanted = dict(expected_terms(label))
    if label.get("terms") is not None:
        terms = {
            "net_days": wanted["net_days"],
            "discount_bps": wanted.get("discount_bps"),
            "discount_days": wanted.get("discount_days"),
            "late_fee": None
            if "late_fee.kind" not in wanted
            else {
                "kind": wanted["late_fee.kind"],
                "rate_bps": wanted["late_fee.rate_bps"],
                "period_days": wanted["late_fee.period_days"],
            },
            "uncertain": False,
        }
    units = int(label["amount"])
    return {
        "vendor_name": _located(label["vendor_name"]),
        "invoice_no": _located(label["invoice_no"]),
        "issue_date": _located(label["issue_date"]),
        "due_date": _located(label["due_date"]),
        "amount_text": _located(f"{units // 10**6}.{units % 10**6:06d}"),
        "currency": _located(label["currency"]),
        "payee_address_as_found": _located(label["payee_address"]),
        "terms": terms,
        "invoice_count_in_document": 1,
        "suspicious_instructions": [],
    }


def _write_recordings(directory: Path, cases: list[Case], *, break_currency: str = "") -> None:
    directory.mkdir(parents=True)
    for case in cases:
        answer = _perfect_answer(case.label)
        if case.invoice_id == break_currency:
            answer["currency"] = _located("EUR")
        record = {
            "invoice_id": case.invoice_id,
            "prompt_version": EXTRACT_TEMPLATE.version,
            "model": "test-model",
            "pdf_sha256": case.pdf_sha256,
            "recorded_at": "2026-10-16",
            "responses": [{"text": json.dumps(answer), "input_tokens": 5, "output_tokens": 5}],
        }
        (directory / f"{case.invoice_id}.json").write_text(json.dumps(record))


def _adapter(provider: RecordedProvider) -> AiAdapter:
    return AiAdapter(
        provider=provider,
        config=load_ai_config(REPO_ROOT / "config" / "ai.yaml"),
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )


@pytest.fixture(scope="module")
def cases() -> list[Case]:
    return load_cases(DATASET)


def test_corpus_loads_thirty_labelled_pdfs(cases: list[Case]) -> None:
    assert len(cases) == 30 and all(c.pdf.startswith(b"%PDF") for c in cases)


def test_perfect_recordings_score_one_hundred_percent(cases: list[Case], tmp_path: Path) -> None:
    _write_recordings(tmp_path / "rec", cases)
    scores = run_cases(_adapter(RecordedProvider(tmp_path / "rec", cases)), cases)
    summary = summarize(scores)

    assert summary.failed == 0 and all(v == 1.0 for v in summary.accuracy.values())
    assert summary.terms.f1 == 1.0 and summary.terms_exact == 1.0


def test_one_wrong_answer_lowers_only_its_field(cases: list[Case], tmp_path: Path) -> None:
    _write_recordings(tmp_path / "rec", cases, break_currency="inv-003")
    scores = run_cases(_adapter(RecordedProvider(tmp_path / "rec", cases)), cases)
    summary = summarize(scores)
    report = render_report(scores, summary, mode="recorded", model="m", notes=[])

    assert summary.accuracy["currency"] == pytest.approx(29 / 30)
    assert summary.accuracy["amount"] == 1.0
    assert "| currency | 29/30 | 96.7% |" in report
    assert "inv-003: currency: expected `USDC`, got `EUR`" in report


def test_unparseable_answer_is_a_pipeline_failure_not_a_crash(
    cases: list[Case], tmp_path: Path
) -> None:
    _write_recordings(tmp_path / "rec", cases)
    path = tmp_path / "rec" / "inv-001.json"
    record = json.loads(path.read_text())
    record["responses"] = [{"text": "not json", "input_tokens": 1, "output_tokens": 1}] * 2
    path.write_text(json.dumps(record))
    summary = summarize(run_cases(_adapter(RecordedProvider(tmp_path / "rec", cases)), cases))

    assert summary.failed == 1 and summary.accuracy["invoice_no"] == pytest.approx(29 / 30)


def test_stale_or_missing_recordings_are_refused(cases: list[Case], tmp_path: Path) -> None:
    with pytest.raises(RecordingError, match="no recording"):
        RecordedProvider(tmp_path, cases)

    _write_recordings(tmp_path / "rec", cases)
    path = tmp_path / "rec" / "inv-002.json"
    record = json.loads(path.read_text())
    record["pdf_sha256"] = "0" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(RecordingError, match="different PDF"):
        RecordedProvider(tmp_path / "rec", cases)

    record["pdf_sha256"] = cases[1].pdf_sha256
    record["prompt_version"] = "extract.v0"
    path.write_text(json.dumps(record))
    with pytest.raises(RecordingError, match="re-record"):
        RecordedProvider(tmp_path / "rec", cases)


def test_main_writes_the_report_offline(
    cases: list[Case], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _write_recordings(tmp_path / "rec", cases)
    out = tmp_path / "report.md"

    code = main(["--mode", "recorded", "--recordings", str(tmp_path / "rec"), "--out", str(out)])

    assert code == 0
    text = out.read_text()
    assert "| vendor_name | 30/30 | 100.0% |" in text and "| F1 | 100.0% |" in text


def test_main_fails_cleanly_without_recordings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    code = main(["--recordings", str(tmp_path / "none"), "--out", str(tmp_path / "r.md")])

    assert code == 2 and not (tmp_path / "r.md").exists()
