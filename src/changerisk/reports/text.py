"""Plain terminal output. ASCII only, so it survives any Windows code page."""

from __future__ import annotations

import textwrap

from ..models import Level, RiskReport, Severity, display_ref
from ..rules.base import plural

TAGS = {
    Severity.CRITICAL: "CRIT",
    Severity.HIGH: "HIGH",
    Severity.MEDIUM: "MED",
    Severity.LOW: "LOW",
    Severity.INFO: "INFO",
}
# ANSI 256-colour codes picked to stay legible on both dark and light terminals.
SEVERITY_COLOR = {
    Severity.CRITICAL: "1;38;5;161",
    Severity.HIGH: "1;38;5;166",
    Severity.MEDIUM: "38;5;178",
    Severity.LOW: "38;5;71",
    Severity.INFO: "2",
}
LEVEL_COLOR = {
    Level.CRITICAL: SEVERITY_COLOR[Severity.CRITICAL],
    Level.HIGH: SEVERITY_COLOR[Severity.HIGH],
    Level.MODERATE: SEVERITY_COLOR[Severity.MEDIUM],
    Level.LOW: SEVERITY_COLOR[Severity.LOW],
}


class _Paint:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def __call__(self, code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if self.enabled else text


def _wrap(text: str, width: int, indent: str, first: str | None = None) -> str:
    return textwrap.fill(
        text, width=width, initial_indent=first if first is not None else indent,
        subsequent_indent=indent, break_long_words=False, break_on_hyphens=False,
    )  # fmt: skip


def commits_text(report: RiskReport) -> str:
    n = report.commit_count
    return f", {n} commit{'' if n == 1 else 's'}" if n else ""


def _short_range(report: RiskReport) -> str:
    if report.mode == "range":
        return f"{display_ref(report.base)}...{display_ref(report.head)}"
    return "staged changes" if report.mode == "staged" else "working tree"


def render(
    report: RiskReport, *, color: bool = False, width: int = 100, verbose: bool = False
) -> str:
    paint = _Paint(color)
    out: list[str] = []
    add = out.append

    add(
        paint("1", "ChangeRisk")
        + f"  {report.repo}  {_short_range(report)}"
        + paint("2", f"  ({plural(len(report.files), 'file')}, +{report.additions} -{report.deletions}"
                f"{commits_text(report)})")
    )  # fmt: skip
    add("")
    level = report.level.label.upper()
    gate = "FAILED" if report.gate_failed else ("passed" if report.fail_on != "never" else "off")
    gate_text = f"gate {gate}" + (
        f" (fails at {report.fail_on})" if report.fail_on != "never" else ""
    )
    add(
        f"  RISK  {paint(LEVEL_COLOR[report.level], level)}   score {report.score}/100   {gate_text}"
    )
    add("")
    add(_wrap(report.verdict, width - 2, "  "))
    add(_wrap(report.recommendation, width - 2, "  ", "  Next: "))
    if report.floor_note:
        add(_wrap(report.floor_note, width - 2, "  "))

    if report.findings:
        add("")
        add(paint("1", "  Why this needs extra testing") + paint("2", "  (ranked by points)"))
        shown = report.findings if verbose else report.findings[:8]
        for i, f in enumerate(shown, 1):
            label = f"[{TAGS[f.severity]}]"
            tag = paint(SEVERITY_COLOR[f.severity], label) + " " * (6 - len(label))
            add("")
            add(f"  {i:>2}. {tag} +{f.points:<4.1f} {paint('1', f.title)}")
            add(_wrap(f.detail, width - 2, " " * 10))
            for ev in f.evidence[: (len(f.evidence) if verbose else 2)]:
                where = ev.path + (f":{ev.line}" if ev.line else "")
                mark = "-" if ev.side == "old" else "+"
                add(paint("2", _wrap(f"{where}  {mark} {ev.text}", width - 2, " " * 12, " " * 10)))
            if verbose:
                add(_wrap("Why it matters: " + f.why, width - 2, " " * 10))
        if len(report.findings) > len(shown):
            add("")
            add(
                f"      ... and {len(report.findings) - len(shown)} more (use --verbose or --format json)"
            )

    if report.test_plan:
        add("")
        add(paint("1", "  Test plan"))
        for step in report.test_plan:
            add(_wrap(step.text, width - 2, "        ", f"   [ ] P{step.priority} "))

    flagged = [f for f in report.files if f.points > 0]
    if flagged:
        add("")
        add(paint("1", "  Riskiest files"))
        for fr in flagged[:8]:
            add(
                f"   {fr.points:>5.1f}  {fr.status[:3]:<3}  +{fr.additions:<4} -{fr.deletions:<4} {fr.path}"
            )

    if report.notes:
        add("")
        for note in report.notes:
            add(paint("2", _wrap("Note: " + note, width - 2, "        ", "  ")))
    return "\n".join(out) + "\n"
