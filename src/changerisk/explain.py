"""The written part of the report: verdict, recommendation, test plan, category breakdown."""

from __future__ import annotations

from collections import defaultdict

from .models import Finding, Level, PlanStep, Severity
from .rules.base import CATEGORIES, join_names

LEAD = {
    Level.LOW: "The usual review and test run should be enough.",
    Level.MODERATE: "Run extra tests on the areas below before merging.",
    Level.HIGH: "This change needs extra testing and a careful review before it merges.",
    Level.CRITICAL: "Do not merge until the critical findings are dealt with and the test plan is done.",
}
RECOMMENDATION = {
    Level.LOW: "Normal review. Run the existing suite.",
    Level.MODERATE: "Targeted tests for the flagged areas, then the full suite.",
    Level.HIGH: "Targeted tests, the full suite, and a second reviewer for the flagged files.",
    Level.CRITICAL: "Hold the merge. Resolve the critical findings, then run this check again.",
}
MAX_PLAN = 14


def _phrase(title: str) -> str:
    """Lower-case the first word unless it is an acronym or already lower."""
    head = title.split(" ", 1)[0]
    if len(head) > 1 and head[1].isupper():
        return title
    return title[:1].lower() + title[1:]


def verdict(level: Level, findings: list[Finding], file_count: int, ignored: int = 0) -> str:
    if file_count == 0:
        if ignored:
            return f"All {ignored} changed {'file is' if ignored == 1 else 'files are'} excluded by paths.ignore, so there is nothing to analyse."
        return "No changes to analyse."
    if not findings:
        return f"No risky patterns found in {file_count} changed {'file' if file_count == 1 else 'files'}. {LEAD[Level.LOW]}"
    ranked = sorted(findings, key=lambda f: f.points, reverse=True)
    titles = list(dict.fromkeys(_phrase(f.title.split(":")[0]) for f in ranked))
    lead = LEAD[level]
    top, rest = titles[:3], len(titles) - 3
    named = join_names(top, 3) + (f", plus {rest} more" if rest > 0 else "")
    if level == Level.LOW:
        return f"{lead} Worth a glance: {named}."
    return f"{lead} The main reasons: {named}."


def recommendation(level: Level) -> str:
    return RECOMMENDATION[level]


def _priority(sev: Severity) -> int:
    if sev >= Severity.HIGH:
        return 1
    return 2 if sev == Severity.MEDIUM else 3


def build_test_plan(findings: list[Finding]) -> tuple[list[PlanStep], int]:
    """Merge every finding's test suggestions into one ordered, de-duplicated checklist.

    Returns the steps shown and how many more were left out.
    """
    steps: dict[str, PlanStep] = {}
    for f in sorted(findings, key=lambda f: f.points, reverse=True):
        prio = _priority(f.severity)
        for text in f.test_focus:
            step = steps.get(text)
            if step is None:
                steps[text] = PlanStep(text=text, priority=prio, rules=[f.rule_id])
            else:
                step.priority = min(step.priority, prio)
                if f.rule_id not in step.rules:
                    step.rules.append(f.rule_id)
    ordered = sorted(steps.values(), key=lambda s: s.priority)  # stable: keeps points order inside
    return ordered[:MAX_PLAN], max(0, len(ordered) - MAX_PLAN)


def category_breakdown(findings: list[Finding]) -> list[dict]:
    points: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    worst: dict[str, Severity] = {}
    for f in findings:
        points[f.category] += f.points
        counts[f.category] += 1
        worst[f.category] = max(worst.get(f.category, Severity.INFO), f.severity)
    rows = [
        {
            "id": cid,
            "label": CATEGORIES[cid],
            "points": round(points[cid], 1),
            "findings": counts[cid],
            "top_severity": worst[cid].label,
        }
        for cid in points
    ]
    rows.sort(key=lambda r: (-r["points"], r["label"]))
    return rows
