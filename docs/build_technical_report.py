"""Render the Vietnamese technical report as a self-contained documentation hub.

Run with a Python environment containing markdown-it-py:
    python docs/build_technical_report.py
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import re
import unicodedata

from markdown_it import MarkdownIt


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "TECHNICAL_REPORT_VI.md"
OUTPUT = HERE / "TECHNICAL_REPORT_VI.html"


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return value or "section"


def render() -> None:
    markdown = MarkdownIt("default", {"html": False}).enable("table")
    tokens = markdown.parse(SOURCE.read_text(encoding="utf-8"))
    headings: list[tuple[int, str, str]] = []
    used: dict[str, int] = {}
    for index, token in enumerate(tokens):
        if token.type != "heading_open":
            continue
        title = tokens[index + 1].content
        base = slug(title)
        used[base] = used.get(base, 0) + 1
        anchor = base if used[base] == 1 else f"{base}-{used[base]}"
        token.attrSet("id", anchor)
        headings.append((int(token.tag[1:]), title, anchor))

    body = markdown.renderer.render(tokens, markdown.options, {})
    groups = [
        ("BẮT ĐẦU", [1]),
        ("KIẾN TRÚC & DỮ LIỆU", [2, 8]),
        ("LUỒNG TIỀN", [3, 4, 5, 7]),
        ("AI, CHỨNG CỨ & AN TOÀN", [6, 9, 10, 11]),
        ("VẬN HÀNH", [12, 13, 14, 15]),
    ]
    by_number: dict[int, list[tuple[int, str, str]]] = {}
    current = 0
    for level, title, anchor in headings:
        if level == 2:
            current = int(title.split(" · ", 1)[0])
        if level in (2, 3):
            by_number.setdefault(current, []).append((level, title, anchor))

    nav: list[str] = []
    for group_name, numbers in groups:
        nav.append(f'<div class="nav-group"><p class="nav-label">{escape(group_name)}</p>')
        for number in numbers:
            for level, title, anchor in by_number.get(number, []):
                label = title.split(" · ", 1)[-1] if level == 2 else title
                nav.append(
                    f'<a class="nav-link level-{level}" href="#{escape(anchor)}">'
                    f'{escape(label)}</a>'
                )
        nav.append("</div>")

    html = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="description" content="Báo cáo kỹ thuật TreasuryPilot: kiến trúc, luồng tiền, AI, smart contract, bảo mật và bằng chứng.">
  <title>TreasuryPilot Docs — Technical Report</title>
  <style>
    :root { --ink:#172033; --muted:#626d7f; --line:#e2e7f1; --accent:#185db8; --accent-soft:#eef3ff; --surface:#fff; --page:#fbfcff; --nav-width:300px; }
    * { box-sizing:border-box; }
    html { scroll-behavior:smooth; }
    body { margin:0; color:var(--ink); background:var(--page); font:16px/1.72 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
    a { color:var(--accent); text-decoration:none; }
    a:hover { text-decoration:underline; }
    a:focus-visible, button:focus-visible, input:focus-visible { outline:3px solid #86b3f4; outline-offset:3px; }
    .layout { display:grid; grid-template-columns:var(--nav-width) minmax(0,1fr); min-height:100vh; }
    .sidebar { position:sticky; top:0; height:100vh; overflow-y:auto; background:var(--surface); border-right:1px solid var(--line); padding:26px 18px 50px; scrollbar-width:thin; }
    .brand { display:flex; align-items:center; gap:10px; padding:4px 10px 19px; border-bottom:1px solid var(--line); color:#0c1830; font-weight:780; font-size:19px; line-height:1.25; }
    .brand-mark { display:grid; place-items:center; width:34px; height:34px; border-radius:10px; background:#173e88; color:#fff; font-size:16px; flex:none; }
    .brand small { display:block; color:#8290a2; font-size:11px; font-weight:650; letter-spacing:.12em; text-transform:uppercase; }
    .search { width:100%; margin:20px 0 9px; padding:10px 12px; border:1px solid #dce4f2; border-radius:9px; background:#f8faff; color:var(--ink); font:inherit; font-size:14px; }
    .nav-group { margin:20px 0 27px; }
    .nav-label { margin:0 10px 10px; color:#9aa3b1; font-size:11px; font-weight:800; letter-spacing:.13em; }
    .nav-link { display:block; margin:2px 0; padding:7px 11px; border-left:3px solid transparent; border-radius:7px; color:#4c5668; font-size:14px; line-height:1.4; }
    .nav-link:hover { background:#f5f7fc; text-decoration:none; }
    .nav-link.active { background:var(--accent-soft); border-left-color:var(--accent); color:#1558ad; font-weight:700; }
    .nav-link.level-3 { padding-left:23px; font-size:12.5px; color:#687488; }
    .nav-link.level-3.active { color:#1558ad; }
    .nav-link.hidden { display:none; }
    .content-shell { min-width:0; padding:52px clamp(24px,5vw,100px) 100px; }
    .topline { max-width:1050px; margin:0 auto 21px; display:flex; justify-content:space-between; align-items:center; gap:16px; color:#8791a2; font-size:12px; font-weight:700; letter-spacing:.1em; text-transform:uppercase; }
    .topline .date { color:#60718a; white-space:nowrap; }
    main { max-width:1050px; margin:auto; }
    h1,h2,h3 { color:#111827; line-height:1.2; letter-spacing:-.035em; }
    h1 { font-size:clamp(36px,4.4vw,58px); margin:0 0 27px; font-weight:820; }
    h2 { font-size:29px; margin:76px 0 25px; padding-top:10px; border-top:1px solid var(--line); scroll-margin-top:24px; }
    h3 { font-size:21px; margin:38px 0 16px; scroll-margin-top:28px; }
    main > h1 + blockquote { margin-top:0; }
    blockquote { margin:0 0 28px; padding:22px 27px; background:#f1f4ff; border:1px solid #d9e1fa; border-radius:14px; color:#303c54; }
    blockquote p { margin:0; }
    p { margin:0 0 18px; }
    main > p:nth-of-type(1) { padding:25px 28px; background:#f1f4ff; border:1px solid #d9e1fa; border-radius:14px; font-size:17px; }
    main > p:nth-of-type(2) { color:var(--muted); font-size:14px; }
    ul,ol { padding-left:1.45em; margin:0 0 22px; }
    li { padding-left:.25em; margin:7px 0; }
    code { padding:.12em .34em; border-radius:4px; background:#eef2f8; color:#253e68; font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }
    pre { overflow-x:auto; padding:22px 25px; margin:19px 0 28px; background:#17233a; border-radius:12px; color:#f0f5ff; font-size:13px; line-height:1.55; }
    pre code { padding:0; background:none; color:inherit; }
    table { width:100%; border-collapse:separate; border-spacing:0; margin:22px 0 32px; border:1px solid var(--line); border-radius:11px; overflow:hidden; font-size:14px; line-height:1.55; }
    th,td { padding:12px 14px; border-bottom:1px solid var(--line); border-right:1px solid var(--line); vertical-align:top; }
    tr:last-child td { border-bottom:0; }
    th:last-child,td:last-child { border-right:0; }
    th { text-align:left; background:#f3f6fc; font-weight:720; }
    tr:nth-child(even) td { background:#fcfdff; }
    .mobile-toggle { display:none; }
    .back-top { position:fixed; right:23px; bottom:22px; padding:9px 14px; border:1px solid #d9e1ee; background:#fff; border-radius:9px; box-shadow:0 8px 24px #263c6018; font-size:13px; }
    @media (max-width:960px) {
      .layout { display:block; }
      .sidebar { position:fixed; left:0; top:0; z-index:20; width:min(84vw,330px); transform:translateX(-105%); box-shadow:10px 0 30px #14294a19; transition:transform .22s ease; }
      .sidebar.open { transform:translateX(0); }
      .mobile-toggle { display:block; position:sticky; top:0; z-index:10; width:100%; padding:11px 18px; border:0; border-bottom:1px solid var(--line); background:#fff; text-align:left; color:#173e88; font:700 14px system-ui; }
      .content-shell { padding:30px 22px 90px; }
      .topline { font-size:10px; }
      h2 { margin-top:58px; }
    }
    @media print {
      .layout { display:block; } .sidebar,.mobile-toggle,.back-top { display:none; }
      .content-shell { padding:0; } body { color:#000; background:#fff; font-size:11pt; }
      h1 { font-size:28pt; } h2 { font-size:18pt; page-break-after:avoid; } h3 { page-break-after:avoid; }
      table,pre,blockquote { break-inside:avoid; } a { color:#000; }
    }
  </style>
</head>
<body>
  <button class="mobile-toggle" id="menu-toggle" aria-controls="sidebar" aria-expanded="false">☰ &nbsp;Mục lục báo cáo</button>
  <div class="layout">
    <nav class="sidebar" id="sidebar" aria-label="Mục lục báo cáo">
      <div class="brand"><span class="brand-mark">T</span><span>TreasuryPilot<small>Documentation hub</small></span></div>
      <input class="search" id="nav-search" type="search" placeholder="Tìm trong mục lục…" aria-label="Tìm trong mục lục">
      {{NAV}}
    </nav>
    <div class="content-shell">
      <div class="topline"><span>TECHNICAL REPORT / TREASURYPILOT</span><span class="date">16.10.2026 · v1</span></div>
      <main id="report">{{BODY}}</main>
    </div>
  </div>
  <a class="back-top" href="#report">↑ Lên đầu</a>
  <script>
    const nav = document.getElementById('sidebar');
    const toggle = document.getElementById('menu-toggle');
    toggle.addEventListener('click', () => {
      const open = nav.classList.toggle('open');
      toggle.setAttribute('aria-expanded', String(open));
    });
    document.querySelectorAll('.nav-link').forEach(link => link.addEventListener('click', () => {
      nav.classList.remove('open'); toggle.setAttribute('aria-expanded', 'false');
    }));
    document.getElementById('nav-search').addEventListener('input', event => {
      const term = event.target.value.toLocaleLowerCase('vi').trim();
      document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('hidden', !link.textContent.toLocaleLowerCase('vi').includes(term));
      });
      document.querySelectorAll('.nav-group').forEach(group => {
        group.style.display = group.querySelector('.nav-link:not(.hidden)') ? '' : 'none';
      });
    });
    const links = [...document.querySelectorAll('.nav-link')];
    links[0]?.classList.add('active');
    const watched = links.map(link => document.getElementById(decodeURIComponent(link.hash.slice(1)))).filter(Boolean);
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(e => e.isIntersecting).sort((a,b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (!visible.length) return;
      links.forEach(link => link.classList.toggle('active', link.hash === '#' + visible[0].target.id));
    }, { rootMargin: '-8% 0px -75% 0px' });
    watched.forEach(element => observer.observe(element));
  </script>
</body>
</html>"""
    OUTPUT.write_text(html.replace("{{NAV}}", "\n      ".join(nav)).replace("{{BODY}}", body), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(headings)} headings)")


if __name__ == "__main__":
    render()
