"""The Copilot fidelity runner on scripted fixtures, tampered ones and the committed live run (AGT-016)."""

import json
import shutil
from pathlib import Path

import pytest

from treasurypilot_worker.agent import (
    AiAdapter,
    InMemoryAiCallLog,
    InMemoryBudgetLedger,
    load_ai_config,
)
from treasurypilot_worker.evals.copilot_fidelity import (
    REPO_ROOT,
    RecordedProvider,
    RecordingError,
    load_cases,
    main,
    render_report,
    run_cases,
)

DATASET = REPO_ROOT / "evals" / "copilot"
# Scripted reference answers (not model output): a known-faithful baseline for the scorer.
RECORDINGS = Path(__file__).parent / "fixtures" / "copilot_scripted"
LIVE_REPORT = REPO_ROOT / "docs" / "evidence" / "copilot-fidelity.md"


def _run(recordings: Path) -> list:
    cases = load_cases(DATASET)
    provider = RecordedProvider(recordings, cases)
    adapter = AiAdapter(
        provider=provider,
        config=load_ai_config(REPO_ROOT / "config" / "ai.yaml"),
        ledger=InMemoryBudgetLedger(),
        call_log=InMemoryAiCallLog(),
    )
    return run_cases(adapter, cases, provider)


def test_scripted_answers_cover_all_twenty_cases_faithfully() -> None:
    scores = _run(RECORDINGS)
    assert len(scores) == 20
    assert [s.case_id for s in scores if not s.passed] == []


def test_wrong_number_is_listed_as_a_failure(tmp_path: Path) -> None:
    shutil.copytree(RECORDINGS, tmp_path / "r")
    path = tmp_path / "r" / "cp-001.json"
    record = json.loads(path.read_text())
    expected = load_cases(DATASET)[0].expected["shortage"]
    last = record["responses"][-1]
    last["text"] = last["text"].replace(expected, "90000001")
    path.write_text(json.dumps(record))

    scores = _run(tmp_path / "r")
    failed = [s for s in scores if not s.passed]
    assert [s.case_id for s in failed] == ["cp-001"]
    assert any("missing" in p or "not found" in p or "PostCheck" in p for p in failed[0].problems)
    report = render_report(scores, mode="recorded", model="m", notes=[])
    assert "| cp-001 | FAIL |" in report
    assert "- cp-001:" in report


def test_stale_case_hash_is_refused(tmp_path: Path) -> None:
    shutil.copytree(RECORDINGS, tmp_path / "r")
    path = tmp_path / "r" / "cp-002.json"
    record = json.loads(path.read_text())
    record["case_sha256"] = "0" * 64
    path.write_text(json.dumps(record))
    with pytest.raises(RecordingError, match="different case"):
        RecordedProvider(tmp_path / "r", load_cases(DATASET))


def test_missing_recording_is_refused(tmp_path: Path) -> None:
    with pytest.raises(RecordingError, match="no recording"):
        RecordedProvider(tmp_path, load_cases(DATASET))


def test_main_recorded_writes_report(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    args = ["--mode", "recorded", "--recordings", str(RECORDINGS), "--strict", "--out", str(out)]
    assert main(args) == 0
    assert "numerically faithful: 20/20" in out.read_text()


def test_committed_live_report_is_reproduced_offline(tmp_path: Path) -> None:
    out = tmp_path / "report.md"
    main(["--mode", "recorded", "--out", str(out)])
    assert out.read_text() == LIVE_REPORT.read_text()


def test_live_mode_needs_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert main(["--mode", "live", "--out", str(tmp_path / "r.md")]) == 2
