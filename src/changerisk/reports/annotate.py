"""GitHub workflow commands (annotations) and SARIF."""

from __future__ import annotations

import json

from ..models import Evidence, Finding, RiskReport, Severity
from ..rules.base import all_rules

PER_KIND = 10  # GitHub shows at most 10 annotations of each kind per step

LEVEL_FOR = {
    Severity.CRITICAL: "error",
    Severity.HIGH: "error",
    Severity.MEDIUM: "warning",
    Severity.LOW: "notice",
    Severity.INFO: "notice",
}
SARIF_LEVEL = {"error": "error", "warning": "warning", "notice": "note"}


def _escape_data(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_prop(text: str) -> str:
    return _escape_data(text).replace(":", "%3A").replace(",", "%2C")


def _anchor(f: Finding) -> Evidence | None:
    """The evidence line to pin the annotation to. Removed lines are not in the new file."""
    for ev in f.evidence:
        if ev.side == "new" and ev.line:
            return ev
    return None


def annotations(report: RiskReport) -> str:
    counts = {"error": 0, "warning": 0, "notice": 0}
    lines = []
    for f in report.findings:
        kind = LEVEL_FOR[f.severity]
        if counts[kind] >= PER_KIND:
            continue
        counts[kind] += 1
        props = [f"title={_escape_prop(f'ChangeRisk {f.rule_id}: {f.title}')}"]
        anchor = _anchor(f)
        if anchor is not None:
            props = [f"file={_escape_prop(anchor.path)}", f"line={anchor.line}", *props]
        elif f.paths:
            props = [f"file={_escape_prop(f.paths[0])}", *props]
        lines.append(f"::{kind} {','.join(props)}::{_escape_data(f.detail)}")
    return "\n".join(lines) + ("\n" if lines else "")


def sarif(report: RiskReport) -> str:
    used = {f.rule_id for f in report.findings}
    rules = []
    for rule in all_rules():
        if rule.info.id not in used:
            continue
        info = rule.info
        rules.append(
            {
                "id": info.id,
                "name": info.name.replace(" ", ""),
                "shortDescription": {"text": info.name},
                "fullDescription": {"text": info.why},
                "help": {"text": "What to test:\n- " + "\n- ".join(info.tests)},
                "defaultConfiguration": {"level": SARIF_LEVEL[LEVEL_FOR[info.severity]]},
                "properties": {"category": info.category},
            }
        )
    results = []
    for f in report.findings:
        result: dict = {
            "ruleId": f.rule_id,
            "level": SARIF_LEVEL[LEVEL_FOR[f.severity]],
            "message": {"text": f.detail},
            "properties": {"points": round(f.points, 1), "severity": f.severity.label},
        }
        anchor = _anchor(f)
        path = anchor.path if anchor else (f.paths[0] if f.paths else None)
        if path:
            loc: dict = {"artifactLocation": {"uri": path}}
            if anchor:
                loc["region"] = {"startLine": anchor.line}
            result["locations"] = [{"physicalLocation": loc}]
        results.append(result)
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {"name": "ChangeRisk", "version": report.tool_version, "rules": rules}
                },
                "results": results,
                "properties": {"score": report.score, "level": report.level.label},
            }
        ],
    }
    return json.dumps(doc, indent=2) + "\n"
