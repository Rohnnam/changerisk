"""Markdown for pull request comments and the Actions step summary."""

from __future__ import annotations

from ..models import RiskReport
from ..rules.base import plural

MARKER = "<!-- changerisk-report -->"
COMMENT_LIMIT = 60000  # GitHub rejects comments over 65,536 characters
MAX_REASONS = 10


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _code(text: str) -> str:
    """Inline code that survives backticks in the text."""
    fence = "``" if "`" in text else "`"
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def _commits(report: RiskReport) -> str:
    n = report.commit_count
    return f", {n} commit{'' if n == 1 else 's'}" if n else ""


def _range(report: RiskReport) -> str:
    if report.mode == "range":
        return f"{report.base}...{report.head}"
    return "staged changes" if report.mode == "staged" else "working tree"


def render(report: RiskReport, *, marker: bool = True, link: str | None = None) -> str:
    out: list[str] = []
    add = out.append
    if marker:
        add(MARKER)
    level = report.level.label.capitalize()
    add(f"## ChangeRisk: {level} risk ({report.score}/100)")
    add("")
    add(f"> {report.verdict}")
    add("")
    gate = (
        f"**Failed.** {report.gate_reason}"
        if report.gate_failed
        else (report.gate_reason if report.fail_on == "never" else f"Passed. {report.gate_reason}")
    )
    add("| | |")
    add("|---|---|")
    add(f"| Gate | {_cell(gate)} |")
    add(f"| Next step | {_cell(report.recommendation)} |")
    add(
        f"| Change | {_code(_range(report))}, {plural(len(report.files), 'file')}, "
        f"+{report.additions} -{report.deletions}"
        f"{_commits(report)} |"
    )
    if report.floor_note:
        add(f"| Note | {_cell(report.floor_note)} |")
    add("")

    if report.findings:
        add("### Why this needs extra testing")
        add("")
        for i, f in enumerate(report.findings[:MAX_REASONS], 1):
            add(f"{i}. **{f.title}** ({f.severity.label}, +{f.points:.1f} points)  ")
            add(f"   {f.detail}")
            for ev in f.evidence[:3]:
                where = ev.path + (f":{ev.line}" if ev.line else "")
                mark = "-" if ev.side == "old" else "+"
                add(f"   - {_code(where)} {mark} {_code(ev.text)}")
            tests = f.test_focus[:3]
            if tests or f.why:
                add("   <details><summary>Why it matters and what to test</summary>")
                add("")
                add(f"   {f.why}")
                add("")
                for t in tests:
                    add(f"   - {t}")
                add("")
                add("   </details>")
        if len(report.findings) > MAX_REASONS:
            add("")
            add(
                f"_{len(report.findings) - MAX_REASONS} lower-ranked findings are in the full report._"
            )
        add("")

    if report.test_plan:
        add("### Test plan")
        add("")
        for step in report.test_plan:
            add(f"- [ ] {step.text}")
        add("")

    flagged = [f for f in report.files if f.points > 0][:8]
    if flagged:
        add("### Riskiest files")
        add("")
        add("| File | Status | Lines | Points |")
        add("|---|---|---|---|")
        for fr in flagged:
            add(
                f"| {_code(fr.path)} | {fr.status} | +{fr.additions} -{fr.deletions} | {fr.points:.1f} |"
            )
        add("")

    if report.notes:
        for note in report.notes:
            add(f"_{note}_  ")
        add("")
    foot = f"ChangeRisk {report.tool_version}"
    if link:
        foot = f"[{foot}]({link})"
    add(f"<sub>{foot}. Score {report.score} from {report.points:.1f} points.</sub>")
    text = "\n".join(out) + "\n"
    if len(text) > COMMENT_LIMIT:
        text = (
            text[: COMMENT_LIMIT - 80].rsplit("\n", 1)[0]
            + "\n\n_Report truncated to fit GitHub's comment size limit._\n"
        )
    return text
