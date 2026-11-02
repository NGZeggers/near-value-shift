"""Assemble the static dashboard: one self-contained site/index.html (CSS, JS and data inlined so it opens from file://)."""
from __future__ import annotations

from pathlib import Path

from .config import SITE

WEB = Path(__file__).parent / "web"


def run() -> None:
    data = (SITE / "data.json").read_text()
    html = (WEB / "index.html").read_text()
    html = html.replace("/*STYLE*/", (WEB / "style.css").read_text())
    html = html.replace("/*DATA*/", data.replace("</", "<\\/"))
    html = html.replace("/*APP*/", (WEB / "app.js").read_text())
    (SITE / "index.html").write_text(html)
    (SITE / ".nojekyll").write_text("")
    print(f"site: site/index.html ({len(html) / 1024:,.0f} KB)")
