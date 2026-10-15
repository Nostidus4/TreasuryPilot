from dataclasses import replace

from treasurypilot_core.reconciliation_evidence import (
    ReconciliationFacts,
    is_finalized,
    missing_evidence,
)

OK = ReconciliationFacts(True, True, 2, 0, 0, False, 0, 100, True, True)


def test_complete_evidence() -> None:
    assert missing_evidence(OK, strict=True) == []


def test_each_gap_is_named() -> None:
    assert missing_evidence(replace(OK, approval_valid=False), strict=False) == ["approval"]
    assert missing_evidence(replace(OK, operations_unconfirmed=1), strict=False) == ["operations"]
    assert missing_evidence(replace(OK, stale_lines=1), strict=False) == ["transactions"]
    assert missing_evidence(replace(OK, pay_block=None), strict=False) == ["transactions"]
    assert missing_evidence(replace(OK, verification_discrepancy=True), strict=False) == [
        "verifications"
    ]


def test_document_and_amount_only_block_auto_match() -> None:
    facts = replace(OK, document_hash_ok=False, amount_ok=False)
    assert missing_evidence(facts, strict=False) == []
    assert missing_evidence(facts, strict=True) == ["document", "amount"]


def test_finality_is_inclusive() -> None:
    assert is_finalized(OK, 100)
    assert not is_finalized(OK, 99)
