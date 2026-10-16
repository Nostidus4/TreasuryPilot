# TreasuryPilot report site

This is a trilingual, multi-page documentation site for the existing GitHub Pages
deployment. The current web app remains at the Pages root. The report is built
into `/report/` and works under the repository base path `/TreasuryPilot/`.

## Edit content

- Vietnamese: [`../TECHNICAL_REPORT_VI.md`](../TECHNICAL_REPORT_VI.md)
- English: [`../TECHNICAL_REPORT_EN.md`](../TECHNICAL_REPORT_EN.md)
- Simplified Chinese: [`../TECHNICAL_REPORT_ZH.md`](../TECHNICAL_REPORT_ZH.md)
- Layout/styles: `assets/site.css`, `assets/site.js`
- Editable diagrams: `diagrams/*.drawio`; matching `*.svg` files are used on the site.

Keep the same `##` and `###` heading order in all three Markdown files. Every `##`
chapter and `###` topic becomes a separate page. Source-code and document
references become links to the reviewed GitHub revision; the Google Doc links
continue to open the original document. Update `CODE_SHA` in `build.py` when
the report is reviewed against a new code revision.

Five figures have separate English, Vietnamese and Chinese draw.io sources. The build
copies both the `.drawio` files and exported SVGs into the deployed site.
If a diagram changes, run `python docs/report_site/diagrams/build_diagrams.py`
only when changing the generated layout or translations in that script, then
export every changed `.drawio` file to an SVG with draw.io desktop:

```bash
draw.io -x -f svg -o docs/report_site/diagrams/system-architecture.svg \
  docs/report_site/diagrams/system-architecture.drawio
```

You can also edit a `.drawio` source directly in draw.io and export its SVG.
Commit both files; GitHub Actions uses the committed SVG and does not require
draw.io on the runner. Readers can click a figure for the full-size SVG or
open the editable source link below it.

## Build locally

```bash
python -m pip install -r docs/report_site/requirements.txt
python docs/report_site/build.py
python -m http.server 8765 --directory docs/report-site
```

Open `http://localhost:8765/`; it defaults to English. Use the language switcher
for Vietnamese or Chinese. The generated
`docs/report-site/` directory is ignored by Git because GitHub Actions rebuilds
it from the Markdown and site source. The build validates all local page links.

## Deploy with the existing web app

The existing `.github/workflows/pages.yml` workflow now builds the report into
`apps/web/dist/report` before uploading the Pages artifact. On `main`, changes
to any report Markdown file, this site source, the web app, or the workflow
trigger the deploy. Pull requests run the validation job without publishing.

After GitHub Pages is set to **GitHub Actions**, the expected URLs are:

- Web app: `https://nostidus4.github.io/TreasuryPilot/`
- Report default (English): `https://nostidus4.github.io/TreasuryPilot/report/`
- Vietnamese: `https://nostidus4.github.io/TreasuryPilot/report/vi/`
- English: `https://nostidus4.github.io/TreasuryPilot/report/en/`
- Simplified Chinese: `https://nostidus4.github.io/TreasuryPilot/report/zh/`

The paths are relative inside the report, so navigation also works if a custom
domain is added later. The "Open application" link currently points to the
repository's default GitHub Pages URL; update that link in `build.py` if the
application moves to a custom domain.
