# Labelled synthetic invoices (DOM-004 / #175)

30 PDFs and one exact M20 JSON label per PDF. All vendors and addresses are
synthetic; every page is marked TEST / SYNTHETIC / NO PAYMENT AUTHORITY.
Amounts are six-decimal base-unit strings, dates UTC ISO strings.

| Mix                                         | Cases                                                                                                        |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Discount / late-fee terms                   | inv-001..012 (12 total; 8 discounts, 8 late-fee terms)                                                       |
| Messy rotated table / separate memo layouts | inv-013..018 (6)                                                                                             |
| Two-page documents                          | inv-019..020 (2)                                                                                             |
| Vietnamese text                             | inv-021..024 (4)                                                                                             |
| Expected flags                              | inv-025 changed/unregistered address; inv-026 currency mismatch; inv-027 possible duplicate; inv-028 overdue |

The messy cases are vector text/table layouts, not scanned images or a claim of
OCR robustness. inv-026 deliberately prints EUR while the contextual treasury
asset is USDC. Labels describe printed fields; flags require the context in
`manifest.json`. For inv-027, inv-005 represents an existing paid invoice with
the same vendor/amount and invoice number one edit away. All other cases have
a known baseline and no contextual anomaly in this fixture model.

`label.schema.json` specifies fields/types/enums. The authoring validator checks
the same field contract plus date/term semantics, required mix, PDF existence
and SHA-256. `manifest.json` pins PDF bytes, pages, font identity and review status.
Ground-truth second-person review is pending; extraction accuracy is not measured.

Author with Python + ReportLab 4.4.9:
`python evals/invoices/author.py --font /path/to/Unicode-TrueType.ttf`.
Arial was used for the committed PDFs, with the fingerprint recorded. The font
file is not redistributed. A different font/runtime changes PDF hashes and
requires regenerating/reviewing the manifest. Use `make eval-validate` to check
the committed corpus. Reproduction needs the optional authoring dependency;
consuming the committed fixtures does not need ReportLab.
