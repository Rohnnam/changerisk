"""The standalone HTML report: the dashboard's report view with the data embedded."""

from __future__ import annotations

import json
from html import escape

from ..models import RiskReport
from ..webassets import inline_page, web_dir


def _js_literal(data: object) -> str:
    """JSON that is safe to place inside a <script> element."""
    text = json.dumps(data, ensure_ascii=False)
    return (
        text.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def render(report: RiskReport) -> str:
    payload = {"static": True, "report": report.to_dict()}
    data_script = f"window.__CHANGERISK__ = {_js_literal(payload)};"
    title = f"{report.level.label.capitalize()} risk ({report.score}) \u00b7 {report.head} \u00b7 ChangeRisk"
    return inline_page(web_dir(), data_script, escape(title))
