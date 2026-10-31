"""SIZ001-SIZ003: how big the change is and how widely it spreads."""

from __future__ import annotations

from collections.abc import Iterable

from ..models import FileChange, Finding, Severity
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register

SIZ001 = RuleInfo(
    id="SIZ001",
    name="Large change",
    category="size",
    severity=Severity.MEDIUM,
    summary="Many lines changed, not counting docs, lockfiles and generated files.",
    why=(
        "Review quality drops sharply with size, and large changes mix several ideas so a "
        "regression is hard to trace to its cause."
    ),
    tests=(
        "Split the change into independent pieces and test each on its own",
        "Run the full suite and an exploratory pass over the features it touches",
    ),
    options={"medium_lines": 400, "high_lines": 1000},
)
SIZ002 = RuleInfo(
    id="SIZ002",
    name="Change spans many areas",
    category="size",
    severity=Severity.MEDIUM,
    summary="Files in many different top-level modules changed together.",
    why=(
        "A change that reaches across modules is more likely to break an assumption one of them "
        "makes about another."
    ),
    tests=(
        "Run integration tests that cross the touched module boundaries",
        "Ask an owner of each area to check their part",
    ),
    options={"areas": 5},
)
SIZ003 = RuleInfo(
    id="SIZ003",
    name="Very large single-file change",
    category="size",
    severity=Severity.MEDIUM,
    summary="One file has a very large diff.",
    why=(
        "A diff that big in one file is hard to read in a review tool, and reviewers tend to "
        "skim it."
    ),
    tests=(
        "Read the file top to bottom instead of the diff",
        "Check that every public function in it still has a test",
    ),
    options={"file_lines": 300},
)


def _countable(ctx: Context) -> list[FileChange]:
    return [
        f
        for f in ctx.files
        if not f.binary
        and f.changed_lines
        and not ctx.paths.is_doc(f.path)
        and not ctx.paths.is_generated(f.path)
    ]


@register
class LargeChange(Rule):
    info = SIZ001

    def check(self, ctx: Context) -> Iterable[Finding]:
        opts = ctx.options(self.info)
        files = _countable(ctx)
        total = sum(f.changed_lines for f in files)
        if total < int(opts["medium_lines"]):
            return
        files.sort(key=lambda f: f.changed_lines, reverse=True)
        yield ctx.finding(
            self.info,
            detail=f"{plural(total, 'line')} changed across {plural(len(files), 'file')}.",
            paths=[f.path for f in files],
            evidence=[evidence(f.path, None, f"{f.changed_lines} lines changed") for f in files],
            bump=1 if total >= int(opts["high_lines"]) else 0,
            scope="change",
        )


@register
class SpreadAcrossAreas(Rule):
    info = SIZ002

    def check(self, ctx: Context) -> Iterable[Finding]:
        limit = int(ctx.options(self.info)["areas"])
        areas: dict[str, list[FileChange]] = {}
        for f in _countable(ctx):
            areas.setdefault(ctx.paths.area(f.path), []).append(f)
        if len(areas) < limit:
            return
        ranked = sorted(areas.items(), key=lambda kv: -sum(f.changed_lines for f in kv[1]))
        yield ctx.finding(
            self.info,
            detail=f"The change touches {len(areas)} areas: {join_names([a for a, _ in ranked], 4)}.",
            paths=[f.path for _, fs in ranked for f in fs],
            evidence=[
                evidence(
                    fs[0].path,
                    None,
                    f"{name}: {sum(f.changed_lines for f in fs)} lines in {plural(len(fs), 'file')}",
                )
                for name, fs in ranked
            ],
            scope="change",
        )


@register
class HugeFileDiff(Rule):
    info = SIZ003

    def check(self, ctx: Context) -> Iterable[Finding]:
        limit = int(ctx.options(self.info)["file_lines"])
        big = [f for f in _countable(ctx) if f.changed_lines >= limit]
        big.sort(key=lambda f: f.changed_lines, reverse=True)
        for f in big[:3]:
            yield ctx.finding(
                self.info,
                detail=f"{f.path} has {plural(f.changed_lines, 'changed line')} "
                f"({f.additions} added, {f.deletions} removed).",
                paths=[f.path],
                evidence=[evidence(f.path, None, f"{f.changed_lines} lines changed")],
            )
