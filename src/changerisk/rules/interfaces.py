"""API001-API002: public interfaces and published contracts."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from ..models import ADDED, DELETED, Finding, Severity
from ..paths import matches_any
from .base import Context, Rule, RuleInfo, evidence, join_names, register

API001 = RuleInfo(
    id="API001",
    name="Public interface changed",
    category="interfaces",
    severity=Severity.MEDIUM,
    summary="A public function or class was removed or given a different signature.",
    why=(
        "Callers outside the file, and outside the repository, depend on the old signature. "
        "Nothing in this diff shows who they are."
    ),
    tests=(
        "Search the codebase and dependent repositories for callers of each changed symbol",
        "Keep the old name working for one release with a deprecation warning",
    ),
    options={"many": 5},
)
API002 = RuleInfo(
    id="API002",
    name="API contract changed",
    category="interfaces",
    severity=Severity.MEDIUM,
    summary="An OpenAPI, protobuf, GraphQL or Avro schema changed.",
    why=(
        "Contracts are shared with clients that deploy on their own schedule. Removing or "
        "renumbering a field breaks them without any error on this side."
    ),
    tests=(
        "Run contract tests or a schema diff tool (such as buf breaking or oasdiff) against the previous version",
        "Test an old client against the new server",
    ),
)

_CONTRACTS = (
    "openapi*.y*ml", "openapi*.json", "swagger*.y*ml", "swagger*.json", "*.proto", "*.graphql",
    "*.gql", "*.avsc", "asyncapi*.y*ml",
)  # fmt: skip

_PATTERNS: dict[str, re.Pattern[str]] = {
    "python": re.compile(r"^(?:async\s+)?(?:def|class)\s+([A-Za-z][\w]*)"),
    "javascript": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    "typescript": re.compile(r"^export\s+(?:default\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    "go": re.compile(r"^func\s+(?:\([^)]*\)\s*)?([A-Z]\w*)\s*[(\[]"),
}  # fmt: skip


def public_symbols(lines: Iterable[tuple[int, str]], language: str) -> dict[str, tuple[int, str]]:
    pattern = _PATTERNS[language]
    out: dict[str, tuple[int, str]] = {}
    for no, text in lines:
        m = pattern.match(text)
        if m:
            out[m.group(1)] = (no, text)
    return out


def _normal(text: str) -> str:
    text = re.sub(r"\s+", "", text)
    return text.rstrip(":{")


@register
class PublicInterface(Rule):
    info = API001

    def check(self, ctx: Context) -> Iterable[Finding]:
        # A symbol that vanishes from one file and shows up in another was moved, not removed.
        moved: set[str] = set()
        per_file: dict[str, tuple[dict, dict]] = {}
        for fc in ctx.files:
            lang = ctx.paths.language(fc.path)
            if fc.binary or lang not in _PATTERNS or not ctx.paths.is_source(fc.path):
                continue
            old = public_symbols(((ln.old_no or 0, ln.text) for ln in fc.removed_lines()), lang)
            new = public_symbols(
                ((ln.new_no or 0, ln.text) for ln in ctx.added(fc, self.info.id)), lang
            )
            if lang == "python":
                old = {k: v for k, v in old.items() if not k.startswith("_")}
                new = {k: v for k, v in new.items() if not k.startswith("_")}
            per_file[fc.path] = (old, new)
            moved |= set(new) - set(old)
        many = int(ctx.options(self.info)["many"])
        for fc in ctx.files:
            if fc.path not in per_file:
                continue
            old, new = per_file[fc.path]
            removed = [n for n in old if n not in new and n not in moved]
            resigned = [n for n in old if n in new and _normal(old[n][1]) != _normal(new[n][1])]
            if not removed and not resigned:
                continue
            bits = []
            if removed:
                bits.append(
                    f"removed {join_names([n + '()' if '(' in old[n][1] else n for n in removed])}"
                )
            if resigned:
                bits.append(
                    "changed the signature of "
                    + join_names([n + "()" if "(" in new[n][1] else n for n in resigned])
                )
            ev = [evidence(fc.path, old[n][0], old[n][1], "old") for n in removed]
            ev += [evidence(fc.path, new[n][0], new[n][1]) for n in resigned]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {' and '.join(bits)}.",
                paths=[fc.path],
                evidence=ev,
                bump=1 if len(removed) + len(resigned) >= many else 0,
            )


@register
class ContractChanged(Rule):
    info = API002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or not matches_any(PurePosixPath(fc.path).name, _CONTRACTS):
                continue
            removed = [
                ln
                for ln in fc.removed_lines()
                if ln.text.strip() and not ln.text.lstrip().startswith(("#", "//", "description"))
            ]
            if fc.status == DELETED:
                detail = f"{fc.path} was deleted."
            elif fc.status == ADDED:
                detail = f"{fc.path} was added."
            elif removed:
                detail = f"{fc.path} changed and {len(removed)} of its lines were removed."
            else:
                detail = f"{fc.path} changed (additions only)."
            ev = [evidence(fc.path, ln.old_no, ln.text, "old") for ln in removed]
            ev += [
                evidence(fc.path, ln.new_no, ln.text) for ln in fc.added_lines() if ln.text.strip()
            ]
            yield ctx.finding(
                self.info,
                detail=detail,
                paths=[fc.path],
                evidence=ev,
                bump=1 if removed and fc.status != ADDED else 0,
            )
