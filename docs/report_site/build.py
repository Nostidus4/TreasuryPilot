"""Build the trilingual, multi-page TreasuryPilot report for GitHub Pages.

    python -m pip install -r docs/report_site/requirements.txt
    python docs/report_site/build.py
    python docs/report_site/build.py --output apps/web/dist/report

All site links are relative so the result works beneath a repository Pages base path.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from pathlib import Path
import posixpath
import re
import shutil
import unicodedata
from urllib.parse import unquote, urlsplit

from markdown_it import MarkdownIt
from markdown_it.token import Token


REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
ASSETS = Path(__file__).resolve().parent / "assets"
DIAGRAMS = Path(__file__).resolve().parent / "diagrams"
DEFAULT_OUTPUT = DOCS / "report-site"
CODE_SHA = "50b1117"  # Match the reviewed revision in both source reports.
GITHUB = "https://github.com/Nostidus4/TreasuryPilot"
LANGS = ("en", "vi", "zh")
LANG_NAMES = {"en": "English", "vi": "Tiếng Việt", "zh": "简体中文"}
LANG_TAGS = {"en": "en", "vi": "vi", "zh": "zh-CN"}

LABELS = {
    "vi": {
        "home": "Trang chủ báo cáo",
        "app": "Mở ứng dụng",
        "search": "Tìm trong mục lục…",
        "menu": "Mục lục",
        "topic": "Nội dung trong mục này",
        "overview": "Tổng quan mục",
        "previous": "Trang trước",
        "next": "Trang tiếp",
        "back": "Về đầu trang",
        "read": "Đọc chi tiết",
        "categories": [
            ("BẮT ĐẦU", [1]),
            ("KIẾN TRÚC", [2]),
            ("HÓA ĐƠN & QUỸ", [3, 4, 5]),
            ("AI & THỰC THI", [6, 7]),
            ("DỮ LIỆU, BẰNG CHỨNG & AN TOÀN", [8, 9, 10, 11]),
            ("VẬN HÀNH", [12, 13, 14, 15]),
        ],
    },
    "en": {
        "home": "Report home",
        "app": "Open application",
        "search": "Search the contents…",
        "menu": "Contents",
        "topic": "Topics in this section",
        "overview": "Section overview",
        "previous": "Previous page",
        "next": "Next page",
        "back": "Back to top",
        "read": "Read more",
        "categories": [
            ("GETTING STARTED", [1]),
            ("ARCHITECTURE", [2]),
            ("INVOICES & TREASURY", [3, 4, 5]),
            ("AI & EXECUTION", [6, 7]),
            ("DATA, EVIDENCE & SAFETY", [8, 9, 10, 11]),
            ("OPERATIONS", [12, 13, 14, 15]),
        ],
    },
    "zh": {
        "home": "报告首页",
        "app": "打开应用",
        "search": "搜索目录…",
        "menu": "目录",
        "topic": "本章主题",
        "overview": "章节概览",
        "previous": "上一页",
        "next": "下一页",
        "back": "返回顶部",
        "read": "阅读详情",
        "categories": [
            ("入门", [1]),
            ("架构", [2]),
            ("发票与资金", [3, 4, 5]),
            ("AI 与执行", [6, 7]),
            ("数据、证据与安全", [8, 9, 10, 11]),
            ("运营", [12, 13, 14, 15]),
        ],
    },
}


@dataclass
class Page:
    key: str
    title: str
    tokens: list[Token]
    section: int = 0
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    path: str = ""


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-") or "page"


def heading_text(tokens: list[Token], index: int) -> str:
    return tokens[index + 1].content


def headings(tokens: list[Token], tag: str, start: int = 0, end: int | None = None) -> list[int]:
    return [
        i
        for i in range(start, len(tokens) if end is None else end)
        if tokens[i].type == "heading_open" and tokens[i].tag == tag
    ]


def read_pages(lang: str, md: MarkdownIt) -> dict[str, Page]:
    source = DOCS / f"TECHNICAL_REPORT_{lang.upper()}.md"
    tokens = md.parse(source.read_text(encoding="utf-8"))
    h2 = headings(tokens, "h2")
    first_h1 = headings(tokens, "h1")
    intro_start = first_h1[0] + 3 if first_h1 else 0
    pages = {
        "home": Page(
            "home",
            {"vi": "TreasuryPilot — Báo cáo kỹ thuật", "en": "TreasuryPilot — Technical Report", "zh": "TreasuryPilot — 技术报告"}[lang],
            tokens[intro_start : h2[0]],
            path=f"{lang}/index.html",
        )
    }
    for section_number, section_start in enumerate(h2, 1):
        section_end = h2[section_number] if section_number < len(h2) else len(tokens)
        child_starts = headings(tokens, "h3", section_start + 3, section_end)
        section_key = f"s{section_number:02d}"
        section_body_end = child_starts[0] if child_starts else section_end
        pages[section_key] = Page(
            section_key,
            heading_text(tokens, section_start),
            tokens[section_start + 3 : section_body_end],
            section=section_number,
        )
        for child_number, child_start in enumerate(child_starts, 1):
            child_end = child_starts[child_number] if child_number < len(child_starts) else section_end
            child_key = f"s{section_number:02d}-t{child_number:02d}"
            pages[child_key] = Page(
                child_key,
                heading_text(tokens, child_start),
                tokens[child_start + 3 : child_end],
                section=section_number,
                parent=section_key,
            )
            pages[section_key].children.append(child_key)
    return pages


def assign_paths(all_pages: dict[str, dict[str, Page]]) -> None:
    en = all_pages["en"]
    for lang, pages in all_pages.items():
        for index in range(1, 16):
            section_key = f"s{index:02d}"
            section_slug = slug(en[section_key].title.split(" · ", 1)[-1])
            section_path = f"{lang}/{index:02d}-{section_slug}"
            pages[section_key].path = f"{section_path}/index.html"
            for child_no, child_key in enumerate(pages[section_key].children, 1):
                child_title = en[child_key].title
                child_slug = slug(re.sub(r"^\d+\.\d+\s+", "", child_title))
                pages[child_key].path = f"{section_path}/{child_no:02d}-{child_slug}/index.html"


def href(current: Page, target: Page) -> str:
    return posixpath.relpath(target.path, posixpath.dirname(current.path))


def source_url(raw: str, source: Path, current: Page) -> str:
    if raw.startswith(("http://", "https://", "mailto:", "#")):
        return raw
    parsed = urlsplit(raw)
    local = (source.parent / unquote(parsed.path)).resolve()
    if not local.is_relative_to(REPO) or not local.exists():
        raise ValueError(f"Broken source link in {source.name}: {raw}")
    if local.is_relative_to(DIAGRAMS) and local.suffix in {".svg", ".drawio"}:
        return posixpath.relpath(
            f"diagrams/{local.name}", posixpath.dirname(current.path)
        )
    repo_path = local.relative_to(REPO).as_posix()
    kind = "tree" if local.is_dir() else "blob"
    suffix = f"#{parsed.fragment}" if parsed.fragment else ""
    return f"{GITHUB}/{kind}/{CODE_SHA}/{repo_path}{suffix}"


def render_tokens(md: MarkdownIt, tokens: list[Token], source: Path, current: Page) -> str:
    for token in tokens:
        if token.type != "inline" or not token.children:
            continue
        for child in token.children:
            if child.type == "link_open":
                original = child.attrGet("href")
                if original:
                    child.attrSet("href", source_url(original, source, current))
                    if original.startswith(("http://", "https://")) or not original.startswith("#"):
                        child.attrSet("target", "_blank")
                        child.attrSet("rel", "noopener noreferrer")
            elif child.type == "image":
                original = child.attrGet("src")
                if original:
                    child.attrSet("src", source_url(original, source, current))
    return md.renderer.render(tokens, md.options, {})


def page_title(page: Page) -> str:
    return page.title.split(" · ", 1)[-1] if page.key.startswith("s") and "-t" not in page.key else re.sub(r"^\d+\.\d+\s+", "", page.title)


def nav_html(current: Page, pages: dict[str, Page], lang: str) -> str:
    labels = LABELS[lang]
    parts = [
        f'<a class="nav-home {"active" if current.key == "home" else ""}" href="{escape(href(current, pages["home"]))}">{escape(labels["home"])}</a>'
    ]
    for category, numbers in labels["categories"]:
        parts.append(f'<div class="nav-group"><p class="nav-label">{escape(category)}</p>')
        for number in numbers:
            section = pages[f"s{number:02d}"]
            parts.append(
                f'<a class="nav-link level-2 {"active" if current.key == section.key else ""}" '
                f'href="{escape(href(current, section))}">{escape(page_title(section))}</a>'
            )
            for child_key in section.children:
                child = pages[child_key]
                parts.append(
                    f'<a class="nav-link level-3 {"active" if current.key == child.key else ""}" '
                    f'href="{escape(href(current, child))}">{escape(page_title(child))}</a>'
                )
        parts.append("</div>")
    return "\n".join(parts)


def cards(current: Page, pages: dict[str, Page], keys: list[str], lang: str) -> str:
    read = escape(LABELS[lang]["read"])
    return '<div class="card-grid">' + "\n".join(
        f'<a class="topic-card" href="{escape(href(current, pages[key]))}">'
        f'<span class="card-index">{escape(key[1:].replace("-t", "."))}</span>'
        f'<strong>{escape(page_title(pages[key]))}</strong><span class="card-more">{read} →</span></a>'
        for key in keys
    ) + "</div>"


def home_body(current: Page, pages: dict[str, Page], md: MarkdownIt, lang: str) -> str:
    source = DOCS / f"TECHNICAL_REPORT_{lang.upper()}.md"
    intro = render_tokens(md, current.tokens, source, current)
    blocks = [intro]
    for category, numbers in LABELS[lang]["categories"]:
        blocks.append(f'<h2 class="group-heading">{escape(category)}</h2>')
        blocks.append(cards(current, pages, [f"s{number:02d}" for number in numbers], lang))
    return "\n".join(blocks)


def content_body(current: Page, pages: dict[str, Page], md: MarkdownIt, lang: str) -> str:
    source = DOCS / f"TECHNICAL_REPORT_{lang.upper()}.md"
    content = render_tokens(md, current.tokens, source, current)
    if current.children:
        content += f'<h2 class="group-heading">{escape(LABELS[lang]["topic"])}</h2>'
        content += cards(current, pages, current.children, lang)
    return content


def html_page(current: Page, pages: dict[str, Page], all_pages: dict[str, dict[str, Page]], md: MarkdownIt, lang: str) -> str:
    labels = LABELS[lang]
    section = pages.get(current.parent or (f"s{current.section:02d}" if current.section else "home"), pages["home"])
    crumbs = [f'<a href="{escape(href(current, pages["home"]))}">{escape(labels["home"])}</a>']
    if current.parent:
        crumbs.append(f'<a href="{escape(href(current, section))}">{escape(page_title(section))}</a>')
    if current.key != "home":
        crumbs.append(f'<span aria-current="page">{escape(page_title(current))}</span>')
    trail = '<nav class="breadcrumbs" aria-label="Breadcrumb">' + '<span class="chev">›</span>'.join(crumbs) + '</nav>'
    lang_switch = '<div class="languages" aria-label="Language">' + "".join(
        f'<span class="language-current" aria-current="true">{escape(LANG_NAMES[code])}</span>'
        if code == lang else
        f'<a class="language-link" href="{escape(href(current, all_pages[code][current.key]))}" hreflang="{LANG_TAGS[code]}">{escape(LANG_NAMES[code])}</a>'
        for code in LANGS
    ) + '</div>'
    app = (
        f'<a class="app-link" href="https://nostidus4.github.io/TreasuryPilot/" '
        f'target="_blank" rel="noopener noreferrer">{escape(labels["app"])} ↗</a>'
    )
    body = home_body(current, pages, md, lang) if current.key == "home" else content_body(current, pages, md, lang)
    ordered = list(pages)
    position = ordered.index(current.key)
    next_prev = '<nav class="pagination" aria-label="Page navigation">'
    if position > 0:
        prev = pages[ordered[position - 1]]
        next_prev += f'<a href="{escape(href(current, prev))}"><small>← {escape(labels["previous"])}</small><strong>{escape(page_title(prev))}</strong></a>'
    else:
        next_prev += '<span></span>'
    if position + 1 < len(ordered):
        nxt = pages[ordered[position + 1]]
        next_prev += f'<a class="next" href="{escape(href(current, nxt))}"><small>{escape(labels["next"])} →</small><strong>{escape(page_title(nxt))}</strong></a>'
    next_prev += '</nav>'
    asset = posixpath.relpath("assets", posixpath.dirname(current.path))
    title = current.title if current.key == "home" else f"{page_title(current)} — TreasuryPilot Docs"
    subtitle = {"vi": "Báo cáo kỹ thuật", "en": "Technical documentation", "zh": "技术报告"}[lang]
    alternates = "\n".join(
        f'  <link rel="alternate" hreflang="{LANG_TAGS[code]}" href="{escape(href(current, all_pages[code][current.key]))}">'
        for code in LANGS if code != lang
    )
    return f'''<!doctype html>
<html lang="{LANG_TAGS[lang]}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="description" content="{escape(subtitle)}: architecture, financial engine, AI, contracts, security and evidence.">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{escape(asset)}/site.css">
{alternates}
  <script src="{escape(asset)}/site.js" defer></script>
</head>
<body>
  <button class="mobile-toggle" id="menu-toggle" aria-controls="sidebar" aria-expanded="false">☰ &nbsp;{escape(labels["menu"])}</button>
  <div class="layout">
    <aside class="sidebar" id="sidebar">
      <div class="brand"><span class="brand-mark">T</span><span>TreasuryPilot<small>Documentation hub</small></span></div>
      <div class="sidebar-controls">{lang_switch}{app}</div>
      <label class="sr-only" for="nav-search">{escape(labels["search"])}</label>
      <input class="search" id="nav-search" type="search" placeholder="{escape(labels["search"])}">
      <nav aria-label="{escape(labels["menu"])}">{nav_html(current, pages, lang)}</nav>
    </aside>
    <div class="content-shell">
      <div class="topline"><span>TECHNICAL REPORT / TREASURYPILOT</span><span>16.10.2026 · {lang.upper()}</span></div>
      {trail}
      <main id="top" class="article">
        <div class="eyebrow">{escape(subtitle)}</div>
        <h1>{escape(page_title(current))}</h1>
        {body}
        {next_prev}
      </main>
      <footer>© TreasuryPilot · Reviewed at commit {CODE_SHA} · <a href="{escape(href(current, pages["home"]))}">{escape(labels["home"])}</a> · <a class="back-top" href="#top">↑ {escape(labels["back"])}</a></footer>
    </div>
  </div>
</body>
</html>'''


def landing_page() -> str:
    return '''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url=en/index.html"><link rel="canonical" href="en/index.html">
<title>TreasuryPilot — Technical Report</title></head>
<body><p><a href="en/index.html">Open the English technical report</a></p></body></html>'''


class Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        props = dict(attrs)
        for name in ("href", "src"):
            if props.get(name):
                self.hrefs.append(props[name] or "")


def validate(output: Path) -> None:
    errors: list[str] = []
    for page in output.rglob("*.html"):
        parser = Links()
        parser.feed(page.read_text(encoding="utf-8"))
        for link in parser.hrefs:
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            path = unquote(urlsplit(link).path)
            if not (page.parent / path).resolve().exists():
                errors.append(f"{page.relative_to(output)} → {link}")
    if errors:
        raise ValueError("Broken generated links:\n" + "\n".join(errors[:30]))


def build(output: Path) -> None:
    md = MarkdownIt("default", {"html": False}).enable("table")
    all_pages = {lang: read_pages(lang, md) for lang in LANGS}
    if any(list(all_pages[lang]) != list(all_pages["en"]) for lang in LANGS):
        raise ValueError("English, Vietnamese and Chinese heading structures do not match")
    if len([key for key in all_pages["en"] if key.startswith("s") and "-t" not in key]) != 15:
        raise ValueError("Expected 15 report sections in each language")
    assign_paths(all_pages)
    if output.exists():
        shutil.rmtree(output)
    (output / "assets").mkdir(parents=True)
    shutil.copyfile(ASSETS / "site.css", output / "assets/site.css")
    shutil.copyfile(ASSETS / "site.js", output / "assets/site.js")
    (output / "diagrams").mkdir()
    for diagram in DIAGRAMS.iterdir():
        if diagram.suffix in {".svg", ".drawio"}:
            shutil.copyfile(diagram, output / "diagrams" / diagram.name)
    (output / ".nojekyll").touch()
    (output / "index.html").write_text(landing_page(), encoding="utf-8")
    for lang, pages in all_pages.items():
        for page in pages.values():
            target = output / page.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(html_page(page, pages, all_pages, md, lang), encoding="utf-8")
    validate(output)
    count = sum(1 for _ in output.rglob("*.html"))
    print(f"Built {count} HTML pages in {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    build(args.output.resolve())
