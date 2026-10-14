# Labelled synthetic invoices (DOM-004 / #175)

30 PDFs and one exact M20 JSON label per PDF. All vendors and addresses are
synthetic; every page is marked TEST / SYNTHETIC / NO PAYMENT AUTHORITY.
Amounts are six-decimal base-unit strings, dates UTC ISO strings.

| Mix                                         | Cases                                                                                                                     |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Discount / late-fee terms                   | inv-001..012 (12 total; 8 discounts, 8 late-fee terms)                                                                    |
| Messy rotated table / separate memo layouts | inv-013..018 (6)                                                                                                          |
| Two-page documents                          | inv-019..020 (2)                                                                                                          |
| Vietnamese text                             | inv-021..024 (4); labels and terms translated, VN number format `1.234,500000` in inv-021..023, English format in inv-024 |
| Expected flags                              | inv-025 changed/unregistered address; inv-026 currency mismatch; inv-027 possible duplicate; inv-028 overdue              |

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

Issue dates and net terms vary (7 to 60 days, issue dates 2026-09-05..2026-10-14) for
inv-006, 011..019, 021..024, 029, 030. inv-001..005 and inv-007..010 keep the
2026-10-01 / 30-day baseline because `evals/redteam` (#179) reuses them and asserts
their printed fields; inv-020 and inv-025..028 also keep it (flag reasoning). All
payees remain the shared registry address. Labels store canonical integer base units;
only the printed amount text differs by locale.

Author with Python + ReportLab 4.4.9:
`python evals/invoices/author.py --font /path/to/Unicode-TrueType.ttf`.
Windows Arial was used for the original PDFs and its fingerprint is the top-level
`font_sha256`. The 16 PDFs revised for vi/date variation were re-rendered with macOS
Arial (the original file was unavailable) via
`author.py --font <Arial.ttf> --only inv-006,...`; each such manifest entry records its
own `font_sha256`, and untouched PDFs are kept byte-for-byte. Fonts are not
redistributed. A different font/runtime changes PDF hashes and requires regenerating/reviewing
the manifest. Use `make eval-validate` to check
the committed corpus. Reproduction needs the optional authoring dependency;
consuming the committed fixtures does not need ReportLab.
