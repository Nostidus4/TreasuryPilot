# TreasuryPilot slide illustrations

Five 16:9, 1920×1080 English visuals are ready to insert into PowerPoint or Google Slides:

| Image | Topic |
|---|---|
| `05-system-architecture.png` | Overall application, services, data and chain boundaries |
| `05A-frontend.png` | User roles, UI flow and actual web stack |
| `05B-backend.png` | API, workers, signer and actual backend stack |
| `05C-data-model.png` | Conceptual data groups and evidence chain |
| `05D-ai-and-controls.png` | AI, deterministic engine, policy and execution authority |

Each image also has an SVG for crisp scaling and a native `.drawio` file for editing. The `.drawio` sources are generated from `build_slides.py`; edit that script to change shared layout, then export with draw.io desktop. The visuals intentionally use the TreasuryPilot stack from the repository, rather than the Node/Express/MongoDB labels in the visual reference. The data-model page is a conceptual grouping, not a literal table-by-table ERD.

```bash
python docs/slide_assets/build_slides.py
/Applications/draw.io.app/Contents/MacOS/draw.io -x -f png \
  -o docs/slide_assets/05-system-architecture.png \
  docs/slide_assets/05-system-architecture.drawio
```

Draw.io adds a small export margin. Crop the exported PNG to 1920×1080 before inserting it in a slide. The committed PNG files have already been cropped.
