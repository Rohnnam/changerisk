"""HIS001-HIS002: what the repository's history says about the files and commits involved."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import Finding, Severity
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register

HIS001 = RuleInfo(
    id="HIS001",
    name="Frequently changed file",
    category="history",
    severity=Severity.MEDIUM,
    summary="A file in the change was edited often and fixed often in the weeks before.",
    why=(
        "Files that change a lot and keep needing fixes are where defects concentrate. Another "
        "edit has a higher chance of being the next fix."
    ),
    tests=(
        "Read the recent fix commits for this file and check this change does not repeat their mistakes",
        "Add a regression test for each previous bug fix that has none",
    ),
    options={"commits": 8, "fix_ratio": 0.4, "max_findings": 4},
)
HIS002 = RuleInfo(
    id="HIS002",
    name="Revert in the range",
    category="history",
    severity=Severity.LOW,
    summary="The commits include a revert, or a re-application of reverted work.",
    why=(
        "A revert means something was released or merged and then pulled back. Bringing the same "
        "change in again tends to reintroduce the original problem."
    ),
    tests=(
        "Find out why the original change was reverted and write a test for that failure",
        "Re-run whatever scenario triggered the revert",
    ),
)

_REVERT = re.compile(r"^\s*Revert\b", re.IGNORECASE)
_REAPPLY = re.compile(r"^\s*(?:Reapply|Re-apply|Revert\s+\"Revert)\b", re.IGNORECASE)


@register
class Hotspot(Rule):
    info = HIS001

    def check(self, ctx: Context) -> Iterable[Finding]:
        if ctx.history is None:
            return
        opts = ctx.options(self.info)
        min_commits = int(opts["commits"])
        min_ratio = float(opts["fix_ratio"])
        ranked = []
        for fc in ctx.files:
            if fc.binary or ctx.paths.is_doc(fc.path) or ctx.paths.is_generated(fc.path):
                continue
            h = ctx.history.get(fc.path)
            if h and h.commits >= min_commits:
                ranked.append((fc, h))
        ranked.sort(key=lambda pair: (pair[1].fixes, pair[1].commits), reverse=True)
        days = ctx.history.days
        for fc, h in ranked[: int(opts["max_findings"])]:
            buggy = h.fixes >= 3 and h.fix_ratio >= min_ratio
            tail = f", {plural(h.fixes, 'of them fix', 'of them fixes')}" if h.fixes else ""
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} changed {h.commits} times in the {days} days before this "
                f"branch by {plural(len(h.authors), 'author')}{tail}.",
                paths=[fc.path],
                evidence=[
                    evidence(
                        fc.path,
                        None,
                        f"{h.commits} commits, {h.fixes} fixes, {len(h.authors)} authors",
                    )
                ],
                bump=1 if buggy else 0,
            )


@register
class RevertInRange(Rule):
    info = HIS002

    def check(self, ctx: Context) -> Iterable[Finding]:
        reverts = [c for c in ctx.changes.commits if _REVERT.match(c.subject)]
        if not reverts:
            return
        reapplied = [c for c in reverts if _REAPPLY.match(c.subject)]
        subjects = join_names([f"'{c.subject}'" for c in reverts], 2)
        yield ctx.finding(
            self.info,
            detail=f"The range includes {plural(len(reverts), 'revert commit')}: {subjects}.",
            paths=[],
            evidence=[evidence("(commit)", None, f"{c.sha[:8]} {c.subject}") for c in reverts],
            bump=1 if reapplied else 0,
            scope="change",
        )
