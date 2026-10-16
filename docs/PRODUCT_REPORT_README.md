# Nine-part product and technical report

`PRODUCT_REPORT_EN.md` follows the nine-section outline supplied for a shareable report. `TreasuryPilot_Product_Technical_Report_EN.docx` is the editable Word export.

To regenerate the DOCX:

```bash
python -m pip install -r docs/docx_requirements.txt
python docs/export_product_report_docx.py
```

The export has an A4 cover, contents, section headings, tables, page numbers and clickable source links to the reviewed code revision. Claims about local Anvil, historical forks, Sepolia deployment, public transactions and production readiness are separated in the text. The slide PNG/SVG/draw.io assets are in `docs/slide_assets/`.
