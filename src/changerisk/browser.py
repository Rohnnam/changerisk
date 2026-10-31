"""Running ChangeRisk inside a web page, through Pyodide (Python compiled to WebAssembly).

A page has no git and no sockets, so this does what the hosted server does minus everything about
being a server: take a pasted diff or a GitHub pull request, fetch what is needed with the page's own
network access, and hand back a report as JSON. Nothing is sent anywhere except to GitHub, and only
when the visitor asks for a pull request.

Errors are returned as `{"error": ..., "status": ...}` rather than raised, because the caller is
JavaScript on the other side of a message channel.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .config import Config
from .engine import analyze_changes
from .models import Level, RiskReport
from .remote import GitHub, SourceError, Transport, load_source, require_trusted
from .reports import render as render_report
from .rules import load_all
from .rules.base import describe_rules

GATES = ("never", "moderate", "high", "critical")
# The standalone HTML report needs the dashboard's files, which this build does not carry.
FORMATS = ("json", "markdown", "sarif", "text")
ANALYSIS_SECONDS = 25.0


def browser_transport() -> Transport:
    """GitHub requests through the page's own network stack (a synchronous XMLHttpRequest).

    Synchronous requests are allowed inside a Web Worker, which is where this runs, and they let
    the same blocking GitHub client serve the server and the browser.
    """

    def fetch(url: str, headers: Any) -> tuple[int, dict[str, str], bytes]:
        require_trusted(url)
        from js import XMLHttpRequest  # exists only inside Pyodide

        request = XMLHttpRequest.new()
        request.open("GET", url, False)
        accept = headers.get("Accept")
        if accept:  # the one header GitHub's CORS policy allows without a preflight
            request.setRequestHeader("Accept", accept)
        try:
            request.send()
        except Exception:
            raise SourceError("Could not reach GitHub. Try again in a moment.", 502) from None
        status = int(request.status)
        if status == 0:
            raise SourceError("Could not reach GitHub. Try again in a moment.", 502)
        received: dict[str, str] = {}
        for line in str(request.getAllResponseHeaders()).strip().splitlines():
            name, _, value = line.partition(":")
            received[name.strip().lower()] = value.strip()
        return status, received, str(request.responseText).encode("utf-8")

    return fetch


def analyze(payload_json: str, transport: Transport | None = None) -> str:
    """Analyse `{"source": {...}, "fail_on": "high"}` and return the report, or an error, as JSON."""
    try:
        payload = json.loads(payload_json)
        source = payload["source"]
        fail_on = payload.get("fail_on", "high")
        if not isinstance(source, dict) or fail_on not in GATES:
            raise ValueError("bad request")
        gh = GitHub(transport=transport or browser_transport())
        changes, config, notes = load_source(gh, source)
        config.fail_on = None if fail_on == "never" else Level.parse(fail_on)
        report = analyze_changes(
            changes,
            config,
            None,
            include_diffs="flagged",
            notes=notes,
            deadline=time.monotonic() + ANALYSIS_SECONDS,
        )
        return json.dumps(report.to_dict())
    except SourceError as exc:  # before ValueError: SourceError is one
        return json.dumps({"error": str(exc), "status": exc.status})
    except (KeyError, TypeError, ValueError):
        return json.dumps({"error": "that request could not be understood", "status": 400})


def rules() -> str:
    """The rule catalogue, as the dashboard's Rules tab expects it."""
    load_all()
    return json.dumps({"rules": describe_rules(Config())})


def render(fmt: str, report_json: str) -> str:
    """Render a report the page holds as Markdown, SARIF, JSON or text."""
    if fmt not in FORMATS:
        raise ValueError(f"format must be one of: {', '.join(FORMATS)}")
    try:
        report = RiskReport.from_dict(json.loads(report_json))
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ValueError("that does not look like a ChangeRisk report") from None
    return render_report(report, fmt)
