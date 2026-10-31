"""Run the rules over a change and assemble the report."""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__, gitops
from . import history as history_mod
from .config import Config, load_config
from .explain import build_test_plan, category_breakdown, recommendation, verdict
from .models import ChangeSet, FileChange, FileReport, Finding, Level, RiskReport
from .redact import redact_line, redact_text
from .rules import load_all
from .rules.base import Context, all_rules, option_defaults
from .scoring import apply_points, score

_UNSET: Any = object()

MAX_FILE_LINES = 600
MAX_TOTAL_LINES = 8000
MAX_TEXT = 400


def run_rules(
    ctx: Context, notes: list[str] | None = None, deadline: float | None = None
) -> list[Finding]:
    load_all()
    found: list[Finding] = []
    for rule in all_rules():
        if deadline is not None and time.monotonic() > deadline:
            if notes is not None:
                notes.append("The time limit was reached, so some rules did not run.")
            break
        settings = ctx.config.rule(rule.info.id)
        if not settings.enabled:
            continue
        try:
            found.extend(rule.check(ctx))
        except Exception as exc:  # a broken rule must not take the whole check down
            message = f"Rule {rule.info.id} failed and was skipped: {type(exc).__name__}: {exc}"
            print(f"changerisk: {message}", file=sys.stderr)
            if notes is not None:
                notes.append(message)
    return found


def _hunks(
    fc: FileChange, budget: int, config_file: bool
) -> tuple[list[dict[str, Any]], bool, int]:
    used = 0
    truncated = False
    out: list[dict[str, Any]] = []
    for h in fc.hunks:
        rows = []
        for ln in h.lines:
            if used >= min(MAX_FILE_LINES, budget):
                truncated = True
                break
            text = redact_line(fc.path, ln.text, config_file=config_file)
            text = text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1] + "…"
            rows.append([ln.kind, ln.old_no, ln.new_no, text])
            used += 1
        if rows:
            out.append(
                {
                    "old_start": h.old_start,
                    "new_start": h.new_start,
                    "header": h.header,
                    "lines": rows,
                }
            )
        if truncated:
            break
    return out, truncated, used


def file_reports(ctx: Context, findings: list[Finding], include_diffs: str) -> list[FileReport]:
    points: dict[str, float] = {}
    ids: dict[str, list[str]] = {}
    for f in findings:
        if f.scope != "file":
            continue  # a finding about the whole change belongs to no single file
        targets = [p for p in f.paths if p in ctx.changed_paths]
        for p in targets:
            points[p] = points.get(p, 0.0) + f.points / len(targets)
            ids.setdefault(p, []).append(f.id)

    reports = []
    budget = MAX_TOTAL_LINES
    ordered = sorted(
        ctx.files, key=lambda fc: (-points.get(fc.path, 0.0), -fc.changed_lines, fc.path)
    )
    for fc in ordered:
        fr = FileReport(
            path=fc.path,
            status=fc.status,
            old_path=fc.old_path,
            additions=fc.additions,
            deletions=fc.deletions,
            binary=fc.binary,
            points=points.get(fc.path, 0.0),
            findings=ids.get(fc.path, []),
        )
        wanted = include_diffs == "all" or (include_diffs == "flagged" and fr.findings)
        if wanted and not fc.binary and fc.hunks and budget > 0:
            fr.hunks, fr.truncated, used = _hunks(fc, budget, ctx.paths.is_config(fc.path))
            budget -= used
        reports.append(fr)
    return reports


def scrub(findings: list[Finding], ctx: Context) -> None:
    """Mask credential-shaped values in anything a finding quotes."""
    for f in findings:
        f.detail = redact_text(f.detail)
        for ev in f.evidence:
            ev.text = redact_line(ev.path, ev.text, config_file=ctx.paths.is_config(ev.path))


def analyze_changes(
    changes: ChangeSet,
    config: Config,
    hist: history_mod.History | None = None,
    *,
    include_diffs: str = "flagged",
    notes: list[str] | None = None,
    deadline: float | None = None,
) -> RiskReport:
    notes = list(notes or [])
    ctx = Context(changes, config, hist)
    findings = run_rules(ctx, notes, deadline)
    scrub(findings, ctx)
    apply_points(findings, config)
    findings.sort(key=lambda f: (-f.points, -f.severity, f.rule_id, f.paths))
    for i, f in enumerate(findings, 1):
        f.id = f"f{i}"

    result = score(findings)
    plan, hidden = build_test_plan(findings)
    if hidden:
        notes.append(f"{hidden} more suggested checks are listed on the individual findings.")
    if ctx.ignored_count:
        notes.append(f"{ctx.ignored_count} files matched paths.ignore and were left out.")
    if changes.truncated:
        notes.append("The diff was larger than the size limit; the end of it was not analysed.")

    fail_on = config.fail_on
    failed = fail_on is not None and result.level >= fail_on
    if fail_on is None:
        reason = "The gate is off."
    elif failed:
        reason = f"Risk level {result.level.label} reached the gate ({fail_on.label})."
    else:
        reason = f"Risk level {result.level.label} is below the gate ({fail_on.label})."

    return RiskReport(
        repo=changes.repo_name,
        base=changes.base,
        head=changes.head,
        mode=changes.mode,
        base_sha=changes.base_sha,
        head_sha=changes.head_sha,
        merge_base=changes.merge_base,
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        tool_version=__version__,
        additions=sum(f.additions for f in ctx.files),
        deletions=sum(f.deletions for f in ctx.files),
        commit_count=len(changes.commits),
        points=result.points,
        score=result.value,
        level=result.level,
        floor_note=result.floor_note,
        verdict=verdict(result.level, findings, len(ctx.files), ctx.ignored_count),
        recommendation=recommendation(result.level),
        fail_on=fail_on.label if fail_on else "never",
        gate_failed=failed,
        gate_reason=reason,
        findings=findings,
        categories=category_breakdown(findings),
        test_plan=plan,
        files=file_reports(ctx, findings, include_diffs),
        commits=changes.commits,
        notes=notes,
        source=changes.source,
    )


def analyze(
    repo: Path | str = ".",
    *,
    base: str | None = None,
    head: str | None = None,
    mode: str = "range",
    config: Config | None = None,
    config_path: Path | None = None,
    use_history: bool | None = None,
    history_days: int | None = None,
    fail_on: Level | str | None = _UNSET,
    include_diffs: str = "flagged",
) -> RiskReport:
    """Analyse a repository. This is the function the CLI, the server and the Action all call."""
    load_all()
    root = gitops.repo_root(repo)
    cfg = config or load_config(root, config_path, option_defaults())
    if fail_on is not _UNSET:
        cfg.fail_on = Level.parse(fail_on) if isinstance(fail_on, str) else fail_on

    changes = gitops.load_changes(root, base, head, mode=mode)
    notes: list[str] = []

    want_history = cfg.history if use_history is None else use_history
    days = history_days or cfg.history_days
    hist = None
    if want_history and changes.merge_base and changes.files:
        if gitops.is_shallow(root):
            notes.append(
                "This is a shallow clone, so history signals were skipped. "
                "Use fetch-depth: 0 in actions/checkout."
            )
        else:
            hist = history_mod.collect(
                root, [f.path for f in changes.files], changes.merge_base, days
            )
            if hist is None:
                notes.append("History signals could not be read and were skipped.")
    return analyze_changes(changes, cfg, hist, include_diffs=include_diffs, notes=notes)
