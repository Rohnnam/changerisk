"""TST001-TST006: tests removed, disabled, weakened or missing."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..models import ADDED, DELETED, FileChange, Finding, Severity
from ..paths import is_comment
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register

TST001 = RuleInfo(
    id="TST001",
    name="Test file deleted",
    category="tests",
    severity=Severity.HIGH,
    summary="A whole test file was removed and its cases do not reappear elsewhere.",
    why=(
        "Tests are the record of behaviour the team decided to keep. Deleting a file removes that "
        "protection for every later change, and nothing fails to tell anyone."
    ),
    tests=(
        "For each case deleted with {path}, name where the behaviour is now covered, or confirm it was removed on purpose",
        "Run the old {path} against the new code to see what it would have caught",
    ),
)
TST002 = RuleInfo(
    id="TST002",
    name="Test cases removed",
    category="tests",
    severity=Severity.MEDIUM,
    summary="Test cases were deleted from a test file that stays.",
    why=(
        "Removing a case is how a failing test gets 'fixed' without fixing the code. Even when it "
        "is legitimate, the behaviour it checked is now unguarded."
    ),
    tests=(
        "Read each case removed from {path} and confirm the behaviour it checked is gone or covered elsewhere",
        "Check the coverage report for lines that only the removed cases reached",
    ),
    options={"high_at": 3},
)
TST003 = RuleInfo(
    id="TST003",
    name="Tests disabled",
    category="tests",
    severity=Severity.MEDIUM,
    summary="Skip, xfail, ignore or focus (.only) markers were added to tests.",
    why=(
        "A skipped test reports nothing, and a focused test (.only) silently skips all the rest. "
        "Both leave the build green while coverage drops."
    ),
    tests=(
        "Run the disabled tests in {path} by hand and record whether they pass",
        "Add a ticket or deadline to every skip so it does not become permanent",
    ),
)
TST004 = RuleInfo(
    id="TST004",
    name="Assertions removed",
    category="tests",
    severity=Severity.MEDIUM,
    summary="Tests keep their names but check less than before.",
    why=(
        "A test with fewer assertions still passes while verifying less. This is the quietest way "
        "to lose coverage."
    ),
    tests=(
        "Compare the old and new assertions in {path} case by case",
        "Mutate the code under test (flip a condition) and confirm the weakened tests still fail",
    ),
    options={"min_drop": 3},
)
TST005 = RuleInfo(
    id="TST005",
    name="Source changed without tests",
    category="tests",
    severity=Severity.MEDIUM,
    summary="Substantial source changes and no test file was touched.",
    why=(
        "New behaviour with no test is unproven, and changed behaviour with no test change means "
        "either the old tests were already vague or they are not running against this code."
    ),
    tests=(
        "Add a test for each changed code path, starting with the largest file in the change",
        "Run the existing suite with coverage and check the changed lines are actually executed",
    ),
    options={"min_lines": 20, "high_lines": 200},
)
TST006 = RuleInfo(
    id="TST006",
    name="Coverage gate lowered",
    category="tests",
    severity=Severity.MEDIUM,
    summary="A minimum-coverage threshold was reduced or removed.",
    why=(
        "A coverage gate is a promise that new code is tested. Lowering it is usually done to get "
        "a build through, and the gap then stays."
    ),
    tests=(
        "Run coverage on the base and head commits and compare the totals",
        "Restore the threshold and add the missing tests instead, if the drop is small",
    ),
)

# --- recognising test cases and assertions ----------------------------------

_PY_CASE = re.compile(r"^\s*(?:async\s+)?def\s+(test\w*)\s*\(")
_JS_CASE = re.compile(r"""^\s*(?:it|test|scenario)(?:\.\w+)*\s*\(\s*(['"`])(.+?)\1""")
_GO_CASE = re.compile(r"^func\s+(Test\w+)\s*\(")
_RUBY_CASE = re.compile(r"""^\s*(?:it|specify|test)\s+['"](.+?)['"]""")
_MARKER = re.compile(
    r"^\s*(?:@(?:Test|ParameterizedTest|RepeatedTest|Fact|Theory)\b|\[(?:Test|TestCase|Fact|Theory|TestMethod)\b|#\[test\])"
)
_METHOD = re.compile(r"\b(?:void|fun|fn|Task|def)\s+(\w+)")

_ASSERT = re.compile(
    r"\bassert\b|\.assert\w*\(|\bassert_\w+\(|\bexpect\(|\.should\b|\bassertThat\(|"
    r"\brequire\.\w+\(|\bt\.(?:Error|Fatal)f?\(|\.to(?:Be|Equal|Have|Contain|Throw|Match)\w*\("
)
_TAUTOLOGY = re.compile(r"^\s*assert\s+(?:True|1)\s*$|expect\(\s*(?:true|1)\s*\)\.to(?:Be|Equal)")

_DISABLERS = (
    (
        re.compile(
            r"@pytest\.mark\.(?:skip|xfail)\b|@unittest\.(?:skip|expectedFailure)\b|\bpytest\.(?:skip|xfail)\("
        ),
        "skip",
    ),
    (re.compile(r"\bself\.skipTest\("), "skip"),
    (
        re.compile(
            r"\b(?:it|test|describe|context)\.(?:skip|todo)\s*\(|\bx(?:it|describe|test)\s*\("
        ),
        "skip",
    ),
    (re.compile(r"\b(?:it|test|describe|context)\.only\s*\(|\bf(?:it|describe)\s*\("), "only"),
    (re.compile(r"\bt\.Skip(?:f|Now)?\("), "skip"),
    (re.compile(r"@(?:Ignore|Disabled)\b|#\[ignore\b|\[Ignore\b"), "skip"),
    (re.compile(r"^\s*(?:skip|pending)\b(?:\s*$|\s+['\"])"), "skip"),
)


def find_cases(items: list[tuple[int, str]], language: str | None) -> list[tuple[int, str]]:
    """Find test cases in (line_no, text) pairs. Returns (line_no, name)."""
    found: list[tuple[int, str]] = []
    for idx, (no, text) in enumerate(items):
        m = None
        if language == "python":
            m = _PY_CASE.match(text)
            name = m.group(1) if m else ""
        elif language in ("javascript", "typescript"):
            m = _JS_CASE.match(text)
            name = m.group(2) if m else ""
        elif language == "go":
            m = _GO_CASE.match(text)
            name = m.group(1) if m else ""
        elif language == "ruby":
            m = _RUBY_CASE.match(text)
            name = m.group(1) if m else ""
        elif _MARKER.match(text):
            name = f"line {no}"
            for _, follow in items[idx + 1 : idx + 4]:
                mm = _METHOD.search(follow)
                if mm:
                    name = mm.group(1)
                    break
            m = True
        if m:
            found.append((no, name))
    return found


def _removed_pairs(fc: FileChange) -> list[tuple[int, str]]:
    return [(ln.old_no or 0, ln.text) for ln in fc.removed_lines()]


def _added_pairs(fc: FileChange) -> list[tuple[int, str]]:
    return [(ln.new_no or 0, ln.text) for ln in fc.added_lines()]


@dataclass
class _FileCases:
    added: list[tuple[int, str]]
    removed: list[tuple[int, str]]


class _CaseLedger:
    """Which test cases left the codebase and which merely moved or were renamed."""

    def __init__(self, ctx: Context) -> None:
        self.added_names: set[str] = set()
        self.per_file: dict[str, _FileCases] = {}
        for fc in ctx.files:
            if fc.binary or not ctx.paths.is_test(fc.path):
                continue
            lang = ctx.paths.language(fc.path)
            cases = _FileCases(
                added=find_cases(_added_pairs(fc), lang),
                removed=find_cases(_removed_pairs(fc), lang),
            )
            self.added_names.update(name for _, name in cases.added)
            self.per_file[fc.path] = cases

    def lost(self, path: str) -> list[tuple[int, str]]:
        """Removed cases whose name is not re-added anywhere, minus a rename allowance."""
        entry = self.per_file.get(path)
        if entry is None:
            return []
        gone = [(no, name) for no, name in entry.removed if name not in self.added_names]
        removed_names = {name for _, name in entry.removed}
        fresh = sum(1 for _, name in entry.added if name not in removed_names)
        allowance = min(len(gone), fresh)
        return gone[: len(gone) - allowance]


@register
class DeletedTestFile(Rule):
    info = TST001

    def check(self, ctx: Context) -> Iterable[Finding]:
        ledger = _CaseLedger(ctx)
        for fc in ctx.files:
            if fc.status != DELETED or not ctx.paths.is_test(fc.path) or fc.binary:
                continue
            entry = ledger.per_file.get(fc.path)
            removed = entry.removed if entry else []
            lost = ledger.lost(fc.path)
            if removed and not lost:
                continue  # every case reappears somewhere else
            if lost:
                detail = f"{fc.path} was deleted, removing {plural(len(lost), 'test case')}."
                ev = [evidence(fc.path, no, f"{name}", "old") for no, name in lost]
            else:
                detail = f"{fc.path} was deleted ({plural(fc.deletions, 'line')})."
                ev = []
            yield ctx.finding(self.info, detail=detail, paths=[fc.path], evidence=ev)


@register
class RemovedTestCases(Rule):
    info = TST002

    def check(self, ctx: Context) -> Iterable[Finding]:
        ledger = _CaseLedger(ctx)
        high_at = int(ctx.options(self.info)["high_at"])
        for fc in ctx.files:
            if fc.status == DELETED or fc.path not in ledger.per_file:
                continue
            lost = ledger.lost(fc.path)
            if not lost:
                continue
            names = join_names([name for _, name in lost])
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} lost {plural(len(lost), 'test case')}: {names}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, no, name, "old") for no, name in lost],
                bump=1 if len(lost) >= high_at else 0,
            )


@register
class DisabledTests(Rule):
    info = TST003

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or fc.status == DELETED or not ctx.paths.is_test(fc.path):
                continue
            lang = ctx.paths.language(fc.path)
            hits: list[tuple[int, str, str]] = []
            for ln in ctx.added(fc, self.info.id):
                if is_comment(ln.text, lang):
                    continue
                for pattern, kind in _DISABLERS:
                    if pattern.search(ln.text):
                        hits.append((ln.new_no or 0, ln.text, kind))
                        break
            if not hits:
                continue
            only = sum(1 for *_, kind in hits if kind == "only")
            parts = []
            if len(hits) - only:
                parts.append(f"{plural(len(hits) - only, 'test')} skipped or ignored")
            if only:
                parts.append(
                    f"{plural(only, 'focus marker')} (.only) that makes the runner skip every other test"
                )
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {' and '.join(parts)}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, no, text) for no, text, _ in hits],
                bump=1 if len(hits) >= 3 or only else 0,
            )


@register
class RemovedAssertions(Rule):
    info = TST004

    def check(self, ctx: Context) -> Iterable[Finding]:
        ledger = _CaseLedger(ctx)
        min_drop = int(ctx.options(self.info)["min_drop"])
        for fc in ctx.files:
            if fc.binary or fc.status in (DELETED, ADDED) or fc.path not in ledger.per_file:
                continue
            if ledger.lost(fc.path):
                continue  # already reported as removed cases
            removed = [ln for ln in fc.removed_lines() if _ASSERT.search(ln.text)]
            added = [ln for ln in ctx.added(fc, self.info.id) if _ASSERT.search(ln.text)]
            tautologies = [ln for ln in ctx.added(fc, self.info.id) if _TAUTOLOGY.search(ln.text)]
            drop = len(removed) - len(added)
            if drop >= min_drop:
                ev = [evidence(fc.path, ln.old_no, ln.text, "old") for ln in removed]
                yield ctx.finding(
                    self.info,
                    detail=f"{fc.path} checks less than before: "
                    f"{plural(len(removed), 'assertion')} removed, {len(added)} added.",
                    paths=[fc.path],
                    evidence=ev,
                )
            elif tautologies:
                yield ctx.finding(
                    self.info,
                    detail=f"{fc.path} gained an assertion that cannot fail.",
                    paths=[fc.path],
                    evidence=[evidence(fc.path, ln.new_no, ln.text) for ln in tautologies],
                )


@register
class UntestedSource(Rule):
    info = TST005

    def check(self, ctx: Context) -> Iterable[Finding]:
        opts = ctx.options(self.info)
        touched_tests = any(ctx.paths.is_test(f.path) and f.status != DELETED for f in ctx.files)
        if touched_tests:
            return
        source = [f for f in ctx.files if ctx.paths.is_source(f.path) and f.changed_lines]
        total = sum(f.changed_lines for f in source)
        if total < int(opts["min_lines"]):
            return
        source.sort(key=lambda f: f.changed_lines, reverse=True)
        yield ctx.finding(
            self.info,
            detail=f"{plural(total, 'line')} changed across {plural(len(source), 'source file')} "
            "and no test file was touched.",
            paths=[f.path for f in source],
            evidence=[evidence(f.path, None, f"{f.changed_lines} lines changed") for f in source],
            bump=1 if total >= int(opts["high_lines"]) else 0,
            scope="change",
        )


_COVERAGE_KEYS = (
    (re.compile(r"\bfail_under\s*[=:]\s*(\d+(?:\.\d+)?)"), "fail_under"),
    (re.compile(r"--cov-fail-under[= ](\d+(?:\.\d+)?)"), "--cov-fail-under"),
    (re.compile(r"\b(?:minimum|min)_coverage\s*[=:]\s*(\d+(?:\.\d+)?)"), "minimum_coverage"),
)
_THRESHOLD_FILES = re.compile(
    r"(?i)^(?:jest|vitest)\.config\..+|\.nycrc.*|\.?codecov\.ya?ml$|package\.json$"
)
_THRESHOLD_KEYS = (
    (re.compile(r"\b(branches|functions|lines|statements)\s*:\s*(\d+(?:\.\d+)?)"), True),
    (re.compile(r"\btarget\s*:\s*(\d+(?:\.\d+)?)%?"), False),
)


def _coverage_values(text: str, name: str) -> dict[str, float]:
    found: dict[str, float] = {}
    for pattern, key in _COVERAGE_KEYS:
        m = pattern.search(text)
        if m:
            found[key] = float(m.group(1))
    if _THRESHOLD_FILES.match(name):
        for pattern, named in _THRESHOLD_KEYS:
            m = pattern.search(text)
            if m:
                key = m.group(1) if named else "target"
                found[key] = float(m.group(2 if named else 1))
    return found


@register
class LoweredCoverageGate(Rule):
    info = TST006

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary:
                continue
            name = PurePosixPath(fc.path).name
            old: dict[str, tuple[float, int | None, str]] = {}
            new: dict[str, tuple[float, int | None, str]] = {}
            for ln in fc.removed_lines():
                for key, val in _coverage_values(ln.text, name).items():
                    old[key] = (val, ln.old_no, ln.text)
            for ln in fc.added_lines():
                for key, val in _coverage_values(ln.text, name).items():
                    new[key] = (val, ln.new_no, ln.text)
            drops = []
            worst = 0.0
            removed_gate = False
            for key, (before, old_no, old_text) in old.items():
                if key in new:
                    after, new_no, new_text = new[key]
                    if after < before:
                        drops.append((key, before, after, evidence(fc.path, new_no, new_text)))
                        worst = max(worst, before - after)
                elif fc.status != DELETED:
                    removed_gate = True
                    drops.append((key, before, None, evidence(fc.path, old_no, old_text, "old")))
            if not drops:
                continue
            bits = [
                f"{key} {'removed' if after is None else f'lowered from {before:g} to {after:g}'}"
                for key, before, after, _ in drops[:3]
            ]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {'; '.join(bits)}.",
                paths=[fc.path],
                evidence=[e for *_, e in drops],
                bump=1 if removed_gate or worst >= 10 else 0,
            )
