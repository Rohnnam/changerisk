"""Output formats."""

from __future__ import annotations

import json

from ..models import RiskReport

FORMATS = ("text", "markdown", "json", "html", "github", "sarif")


def render(
    report: RiskReport, fmt: str, *, color: bool = False, width: int = 100, verbose: bool = False
) -> str:
    if fmt == "text":
        from . import text

        return text.render(report, color=color, width=width, verbose=verbose)
    if fmt == "markdown":
        from . import markdown

        return markdown.render(report)
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"
    if fmt == "github":
        from . import annotate

        return annotate.annotations(report)
    if fmt == "sarif":
        from . import annotate

        return annotate.sarif(report)
    if fmt == "html":
        from . import html

        return html.render(report)
    raise ValueError(f"unknown format {fmt!r} (use one of: {', '.join(FORMATS)})")
