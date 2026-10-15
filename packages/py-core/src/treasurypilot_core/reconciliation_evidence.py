"""Evidence rules for matching a reconciliation (REC-003, M11 §8.3, M11-D2).

Pure: the API (manual match) and the worker (auto-match) each load ``ReconciliationFacts`` from
the database and share this one rule, so the two paths cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReconciliationFacts:
    approval_valid: bool
    attestation_present: bool
    operations: int  # operations of the request
    operations_unconfirmed: int  # ... not Confirmed
    operations_unverified: int  # Confirmed operations without a PASSED verification
    verification_discrepancy: bool
    stale_lines: int  # lines whose transaction or fee no longer matches the chain data
    pay_block: int | None  # block of the EXTERNAL_EXPENSE line
    document_hash_ok: bool  # no document, or one equals the approval invoiceHash
    amount_ok: bool  # PAY amount equals the invoice amount


# One row of facts for the reconciliation ``:rid``. SQLAlchemy runs it as is; asyncpg callers
# replace ``:rid`` with ``$1``. Service code cannot share a query layer, so the SQL lives here.
FACTS_SQL = """
SELECT
  EXISTS (SELECT 1 FROM approvals a WHERE a.request_id = r.request_id AND a.status = 'Valid')
    AS approval_valid,
  -- every operation's step must be covered by an attestation
  ((SELECT count(*) FROM operations o WHERE o.request_id = r.request_id) > 0 AND NOT EXISTS (
     SELECT 1 FROM operations o WHERE o.request_id = r.request_id AND NOT EXISTS (
       SELECT 1 FROM attestations at WHERE o.step_id = ANY(at.step_ids)))) AS attestation_present,
  (SELECT count(*) FROM operations o WHERE o.request_id = r.request_id) AS operations,
  (SELECT count(*) FROM operations o WHERE o.request_id = r.request_id
     AND o.status NOT IN ('Confirmed', 'Abandoned')) AS operations_unconfirmed,
  (SELECT count(*) FROM operations o WHERE o.request_id = r.request_id
     AND o.status = 'Confirmed'
     AND NOT EXISTS (SELECT 1 FROM verifications v
                     WHERE v.operation_id = o.id AND v.result = 'PASSED')) AS operations_unverified,
  EXISTS (SELECT 1 FROM verifications v JOIN operations o ON o.id = v.operation_id
          WHERE o.request_id = r.request_id AND v.result = 'DISCREPANCY')
    AS verification_discrepancy,
  -- A reorg after Paid can leave lines (and FEE lines) the chain data no longer backs.
  (SELECT count(*) FROM reconciliation_lines l WHERE l.reconciliation_id = r.id AND (
     (l.classification <> 'FEE' AND NOT EXISTS (
         SELECT 1 FROM transactions t WHERE t.id = l.transaction_id AND t.status = 'Confirmed'
         AND t.block_number IS NOT DISTINCT FROM l.block_number
         AND t.tx_hash = l.tx_hash))
     OR (l.classification = 'FEE' AND NOT EXISTS (
         SELECT 1 FROM gas_ledger g JOIN transactions t ON t.id = g.transaction_id
         WHERE g.transaction_id = l.transaction_id AND g.fee_wei = l.amount
         AND t.block_number IS NOT DISTINCT FROM l.block_number
         AND t.tx_hash = l.tx_hash)))
  ) + (SELECT count(*) FROM gas_ledger g JOIN transactions t ON t.id = g.transaction_id
       JOIN operations o ON o.id = t.operation_id WHERE o.request_id = r.request_id
       AND NOT EXISTS (SELECT 1 FROM reconciliation_lines l WHERE l.reconciliation_id = r.id
                       AND l.transaction_id = t.id AND l.classification = 'FEE')) AS stale_lines,
  (SELECT max(l.block_number) FROM reconciliation_lines l
     WHERE l.reconciliation_id = r.id AND l.classification = 'EXTERNAL_EXPENSE') AS pay_block,
  -- no document may differ from the request's invoice hash, and the Valid approval signed it
  (NOT EXISTS (SELECT 1 FROM documents d WHERE d.request_id = r.request_id
               AND d.sha256 IS DISTINCT FROM q.invoice_hash)
   AND (q.invoice_hash IS NULL OR EXISTS (
          SELECT 1 FROM approvals a WHERE a.request_id = r.request_id AND a.status = 'Valid'
          AND a.typed_data->'message'->>'invoiceHash' = '0x' || encode(q.invoice_hash, 'hex')))
  ) AS document_hash_ok,
  -- the PAY lines add up to the invoice and went to the request's payee and asset
  (COALESCE((SELECT sum(l.amount) FROM reconciliation_lines l
             WHERE l.reconciliation_id = r.id AND l.classification = 'EXTERNAL_EXPENSE')
            = q.amount, false)
   AND NOT EXISTS (SELECT 1 FROM reconciliation_lines l
                   WHERE l.reconciliation_id = r.id AND l.classification = 'EXTERNAL_EXPENSE'
                   AND (l.to_address IS DISTINCT FROM (SELECT p.address FROM payees p
                                                        WHERE p.id = q.payee_id)
                        OR l.asset_address IS DISTINCT FROM (SELECT x.address FROM assets x
                                                              WHERE x.id = q.asset_id)))
  ) AS amount_ok
FROM reconciliations r JOIN payment_requests q ON q.id = r.request_id
WHERE r.id = :rid
"""


def missing_evidence(facts: ReconciliationFacts, *, strict: bool) -> list[str]:
    """Names of the missing evidence; ``strict`` adds the auto-match-only checks."""

    missing = {
        "approval": not facts.approval_valid,
        "attestation": not facts.attestation_present,
        "operations": facts.operations == 0 or facts.operations_unconfirmed > 0,
        "transactions": facts.pay_block is None or facts.stale_lines > 0,
        "verifications": facts.operations_unverified > 0 or facts.verification_discrepancy,
    }
    if strict:
        missing["document"] = not facts.document_hash_ok
        missing["amount"] = not facts.amount_ok
    return [name for name, absent in missing.items() if absent]


def is_finalized(facts: ReconciliationFacts, finalized_block: int) -> bool:
    return facts.pay_block is not None and facts.pay_block <= finalized_block
