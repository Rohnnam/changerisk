"""CI001-CI003: build and deploy pipeline definitions."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import DELETED, Finding, Severity
from .base import Context, Rule, RuleInfo, evidence, plural, register

CI001 = RuleInfo(
    id="CI001",
    name="Pipeline definition changed",
    category="pipeline",
    severity=Severity.MEDIUM,
    summary="A CI/CD workflow or pipeline file was edited.",
    why=(
        "The pipeline is what decides whether every other change is safe to merge and ship. A "
        "mistake here can pass broken code or block the whole team, and the change itself is "
        "hard to test before it runs for real."
    ),
    tests=(
        "Run the workflow in {path} on a branch and read the logs, not just the final status",
        "Check that a deliberately failing test still turns the pipeline red",
    ),
)
CI002 = RuleInfo(
    id="CI002",
    name="Pipeline checks weakened",
    category="pipeline",
    severity=Severity.HIGH,
    summary="Failures are ignored, a step is disabled, or a test or lint step was removed.",
    why=(
        "A pipeline that cannot fail is decoration. These edits keep the build green while the "
        "code underneath gets less checked."
    ),
    tests=(
        "Push a commit with a failing test and confirm the pipeline fails",
        "Compare the list of steps before and after and account for each missing one",
    ),
)
CI003 = RuleInfo(
    id="CI003",
    name="Workflow permissions or triggers widened",
    category="pipeline",
    severity=Severity.MEDIUM,
    summary="Broader token permissions, risky triggers, or actions pinned to a moving branch.",
    why=(
        "Workflows run with a token and secrets. Wider permissions, triggers that run untrusted "
        "pull request code with secrets, and unpinned third-party actions are how pipelines get "
        "used against their owners."
    ),
    tests=(
        "Read the permissions block and remove anything the job does not need",
        "Pin third-party actions to a commit SHA",
    ),
)

_DEPLOYISH = re.compile(r"(?i)deploy|release|publish|prod|cd\.ya?ml")
_WEAKEN = (
    (re.compile(r"\bcontinue-on-error:\s*true\b"), "failures are ignored (continue-on-error)"),
    (re.compile(r"\ballow_failure:\s*true\b"), "failures are allowed (allow_failure)"),
    (
        re.compile(r"^\s*(?:-\s*)?if:\s*(?:false|\$\{\{\s*false\s*\}\})\s*$"),
        "a job or step is disabled (if: false)",
    ),
    (re.compile(r"\|\|\s*(?:true|exit\s+0|:)\s*$"), "a command's failure is swallowed (|| true)"),
    (re.compile(r"--no-verify\b"), "hooks are skipped (--no-verify)"),
    (re.compile(r"\bset\s+\+e\b"), "the shell no longer stops on errors (set +e)"),
)
_CHECK_COMMAND = re.compile(
    r"\b(?:pytest|py\.test|tox|nox|npm\s+(?:run\s+)?(?:test|lint)|yarn\s+(?:test|lint)|pnpm\s+(?:test|lint)|"
    r"go\s+test|mvn\b[^\n]*\btest|gradle\w*\s+test|cargo\s+(?:test|clippy)|dotnet\s+test|rspec|"
    r"ruff|flake8|pylint|mypy|eslint|golangci-lint|make\s+(?:test|check|lint))\b"
)
_WIDEN = (
    (re.compile(r"^\s*permissions:\s*write-all\b"), "permissions: write-all", 1),
    (
        re.compile(
            r"^\s*(?:contents|packages|actions|id-token|pull-requests|issues|deployments):\s*write\b"
        ),
        "a write permission",
        0,
    ),
    (re.compile(r"\bpull_request_target\b"), "pull_request_target trigger", 1),
    (re.compile(r"^\s*secrets:\s*inherit\b"), "secrets: inherit", 0),
    (
        re.compile(r"\buses:\s*[\w./-]+@(?:main|master|latest|develop|HEAD)\s*$"),
        "an action pinned to a moving branch",
        0,
    ),
)
_PWN = re.compile(r"github\.event\.pull_request\.head\.(?:sha|ref)|github\.head_ref")


def _workflow(path: str) -> bool:
    return path.startswith((".github/workflows/", ".github/actions/"))


@register
class PipelineChanged(Rule):
    info = CI001

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or not ctx.paths.is_pipeline(fc.path) or not fc.changed_lines:
                continue
            ev = [
                evidence(fc.path, ln.new_no, ln.text)
                for ln in fc.added_lines()
                if ln.text.strip() and not ln.text.lstrip().startswith("#")
            ]
            if not ev and fc.status != DELETED:
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} changed ({fc.additions} added, {fc.deletions} removed).",
                paths=[fc.path],
                evidence=ev,
                bump=1 if _DEPLOYISH.search(fc.path) else 0,
            )


@register
class ChecksWeakened(Rule):
    info = CI002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or not ctx.paths.is_pipeline(fc.path):
                continue
            reasons: list[str] = []
            ev = []
            for ln in ctx.added(fc, self.info.id):
                for pattern, label in _WEAKEN:
                    if pattern.search(ln.text):
                        reasons.append(label)
                        ev.append(evidence(fc.path, ln.new_no, ln.text))
                        break
            removed = [ln for ln in fc.removed_lines() if _CHECK_COMMAND.search(ln.text)]
            added_checks = [ln for ln in fc.added_lines() if _CHECK_COMMAND.search(ln.text)]
            if fc.status == DELETED:
                removed, added_checks = [], []  # a deleted pipeline is reported by CI001
            if removed and len(removed) > len(added_checks):
                missing = len(removed) - len(added_checks)
                reasons.append(f"{plural(missing, 'test or lint command')} removed")
                ev += [evidence(fc.path, ln.old_no, ln.text, "old") for ln in removed]
            if not reasons:
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: " + "; ".join(dict.fromkeys(reasons)) + ".",
                paths=[fc.path],
                evidence=ev,
            )


@register
class PermissionsWidened(Rule):
    info = CI003

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or fc.status == DELETED or not _workflow(fc.path):
                continue
            reasons: list[str] = []
            ev = []
            bump = 0
            for ln in ctx.added(fc, self.info.id):
                for pattern, label, step in _WIDEN:
                    if pattern.search(ln.text):
                        reasons.append(label)
                        ev.append(evidence(fc.path, ln.new_no, ln.text))
                        bump = max(bump, step)
                        break
            visible = "\n".join(ln.text for h in fc.hunks for ln in h.lines if ln.kind != "-")
            if any("pull_request_target" in r for r in reasons) and _PWN.search(visible):
                reasons.append("it checks out the pull request's code")
                bump = 2
            if not reasons:
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: " + "; ".join(dict.fromkeys(reasons)) + ".",
                paths=[fc.path],
                evidence=ev,
                bump=bump,
            )
