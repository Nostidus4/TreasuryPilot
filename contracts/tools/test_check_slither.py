"""The security gate must fail on new findings and incomplete analyzer output."""
import json
import tempfile
import unittest
from pathlib import Path

from check_slither import check, fingerprint


class SlitherGateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report = Path(self.directory.name) / "report.json"
        self.triage = Path(self.directory.name) / "triage.json"
        self.triage.write_text(json.dumps({"accepted": []}), encoding="utf-8")

    def test_new_high_finding_blocks(self) -> None:
        self.report.write_text(json.dumps({"success": True, "results": {"detectors": [
            {"impact": "High", "check": "arbitrary-send-erc20", "description": "new unsafe transfer"}
        ]}}), encoding="utf-8")
        self.assertEqual(len(check(self.report, self.triage)), 1)

    def test_incomplete_report_blocks(self) -> None:
        self.report.write_text(json.dumps({"success": False}), encoding="utf-8")
        self.assertTrue(check(self.report, self.triage))

    def test_reviewed_finding_is_specific_and_line_movement_is_stable(self) -> None:
        description = "a sentinel comparison (src/A.sol#123-125)"
        self.triage.write_text(json.dumps({"accepted": [{
            "check": "incorrect-equality", "impact": "Medium", "fingerprint": fingerprint(description),
            "reason": "zero is the explicit sentinel", "evidence": "boundary test"
        }]}), encoding="utf-8")
        finding = {"check": "incorrect-equality", "impact": "Medium", "description": description.replace("123-125", "200-202")}
        self.report.write_text(json.dumps({"success": True, "results": {"detectors": [finding]}}), encoding="utf-8")
        self.assertEqual(check(self.report, self.triage), [])
        finding["description"] = "another, unreviewed equality"
        self.report.write_text(json.dumps({"success": True, "results": {"detectors": [finding]}}), encoding="utf-8")
        self.assertTrue(check(self.report, self.triage))


if __name__ == "__main__":
    unittest.main()
