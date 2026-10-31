"""DEP001-DEP004: dependency manifests and lockfiles."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..models import FileChange, Finding, Severity
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register

DEP001 = RuleInfo(
    id="DEP001",
    name="Dependencies changed",
    category="deps",
    severity=Severity.LOW,
    summary="Packages were added, removed or re-versioned in a manifest.",
    why=(
        "Every dependency is code you did not write and cannot fully review. New packages bring "
        "their own bugs, licences and transitive dependencies."
    ),
    tests=(
        "Install from a clean environment using {path} and run the full suite",
        "Read the release notes of every changed package",
    ),
    options={"many": 5},
)
DEP002 = RuleInfo(
    id="DEP002",
    name="Major version change",
    category="deps",
    severity=Severity.MEDIUM,
    summary="A dependency moved to a different major version, or was downgraded.",
    why=(
        "Major versions are where breaking changes live. Downgrades are rarer and often mean "
        "something broke and was rolled back by hand."
    ),
    tests=(
        "Read the upgrade guide and search the code for each deprecated API it lists",
        "Run the integration tests, not just unit tests, against the new version",
    ),
)
DEP003 = RuleInfo(
    id="DEP003",
    name="Version pin loosened",
    category="deps",
    severity=Severity.MEDIUM,
    summary="An exact version was replaced by a range or removed.",
    why=(
        "A pinned version builds the same way every time. A range means the next install can "
        "pick up a release nobody on the team has tried."
    ),
    tests=(
        "Install twice a week apart and compare the resolved versions",
        "Pin it again, or add a lockfile, unless the range is deliberate",
    ),
)
DEP004 = RuleInfo(
    id="DEP004",
    name="Lockfile not updated",
    category="deps",
    severity=Severity.MEDIUM,
    summary="Dependencies changed in a manifest but the lockfile next to it did not.",
    why=(
        "CI and teammates install from the lockfile. If it disagrees with the manifest, they get "
        "different packages from the ones this change was written against."
    ),
    tests=(
        "Regenerate the lockfile next to {path} and commit it",
        "Run the install step in CI in frozen-lockfile mode to confirm they agree",
    ),
)

LOCKS = {
    "package.json": ("package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "bun.lockb"),
    "pyproject.toml": ("poetry.lock", "uv.lock", "pdm.lock"),
    "pipfile": ("Pipfile.lock",),
    "cargo.toml": ("Cargo.lock",),
    "go.mod": ("go.sum",),
    "gemfile": ("Gemfile.lock",),
    "composer.json": ("composer.lock",),
}  # fmt: skip

_NOT_PACKAGES = {
    "version", "name", "description", "readme", "license", "authors", "main", "module", "types",
    "type", "private", "homepage", "repository", "requires-python", "edition", "keywords",
    "build-backend", "bin", "files", "exports", "browser", "author", "title",
}  # fmt: skip

_OP = r"(?:===?|~=|!=|<=?|>=?)"
_REQ = re.compile(
    rf"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*({_OP}\s*[^;#\s,]+(?:\s*,\s*{_OP}\s*[^;#\s,]+)*)?"
    r"\s*(?:;.*)?(?:#.*)?$"
)
_PEP508_STRING = re.compile(
    r"""^\s*['"]([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*((?:===?|~=|!=|<=?|>=?)[^'";]*)['"]\s*,?\s*(?:#.*)?$"""
)
_TOML_PAIR = re.compile(
    r"""^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*['"]([\^~<>=!*0-9][^'"]*)['"]\s*(?:#.*)?$"""
)
_TOML_TABLE = re.compile(
    r"""^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*=\s*\{.*\bversion\s*=\s*['"]([^'"]+)['"]"""
)
_JSON_PAIR = re.compile(
    r"""^\s*"(@?[A-Za-z0-9][\w./-]*)"\s*:\s*"([\^~<>=*0-9][^"]*|latest|next|git\+[^"]*|file:[^"]*|workspace:[^"]*)"\s*,?\s*$"""
)
_GO = re.compile(r"^\s*(?:require\s+)?([\w.~-]+\.[\w.-]+(?:/[\w.~-]+)+)\s+v(\d[^\s]*)")
_GEM = re.compile(r"""^\s*gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""")
_GRADLE = re.compile(r"""['"]([\w.-]+:[\w.-]+):([\w.+-]+)['"]""")
_VERSION = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?")


@dataclass(frozen=True)
class Dep:
    name: str
    spec: str
    line: int
    text: str

    @property
    def version(self) -> tuple[int, int, int] | None:
        m = _VERSION.search(self.spec)
        if not m:
            return None
        return tuple(int(g or 0) for g in m.groups())  # type: ignore[return-value]

    @property
    def pinned(self) -> bool:
        s = self.spec.strip()
        if s.startswith(("==", "===")):
            return True
        # npm/cargo/gem style: bare version with no range operator
        return bool(re.fullmatch(r"v?\d+(\.\d+){0,2}[\w.+-]*", s)) and not s.startswith(("^", "~"))


def parse_dep(path: str, text: str) -> tuple[str, str] | None:
    name = PurePosixPath(path).name.lower()
    if name.startswith(("requirements", "constraints")) and name.endswith(".txt"):
        if text.lstrip().startswith(("-", "#")) or not text.strip():
            return None
        m = _REQ.match(text)
        return (m.group(1).lower(), (m.group(2) or "").replace(" ", "")) if m else None
    if name == "pyproject.toml":
        m = _PEP508_STRING.match(text)
        if m:
            return m.group(1).lower(), m.group(2).replace(" ", "")
        m = _TOML_PAIR.match(text) or _TOML_TABLE.match(text)
        if m and m.group(1).lower() not in _NOT_PACKAGES:
            return m.group(1).lower(), m.group(2)
        return None
    if name in ("package.json", "composer.json"):
        m = _JSON_PAIR.match(text)
        if m and m.group(1).lower() not in _NOT_PACKAGES:
            return m.group(1), m.group(2)
        return None
    if name == "cargo.toml":
        m = _TOML_PAIR.match(text) or _TOML_TABLE.match(text)
        if m and m.group(1).lower() not in _NOT_PACKAGES:
            return m.group(1), m.group(2)
        return None
    if name == "go.mod":
        m = _GO.match(text)
        return (m.group(1), "v" + m.group(2)) if m else None
    if name == "gemfile":
        m = _GEM.match(text)
        return (m.group(1), m.group(2) or "") if m else None
    if name in ("build.gradle", "build.gradle.kts"):
        m = _GRADLE.search(text)
        return (m.group(1), m.group(2)) if m else None
    return None


@dataclass
class DepDiff:
    added: list[Dep]
    removed: list[Dep]
    changed: list[tuple[Dep, Dep]]

    def __bool__(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    @property
    def count(self) -> int:
        return len(self.added) + len(self.removed) + len(self.changed)


def diff_deps(fc: FileChange) -> DepDiff:
    old: dict[str, Dep] = {}
    new: dict[str, Dep] = {}
    for ln in fc.removed_lines():
        parsed = parse_dep(fc.path, ln.text)
        if parsed:
            old[parsed[0]] = Dep(parsed[0], parsed[1], ln.old_no or 0, ln.text)
    for ln in fc.added_lines():
        parsed = parse_dep(fc.path, ln.text)
        if parsed:
            new[parsed[0]] = Dep(parsed[0], parsed[1], ln.new_no or 0, ln.text)
    return DepDiff(
        added=[new[n] for n in new if n not in old],
        removed=[old[n] for n in old if n not in new],
        changed=[(old[n], new[n]) for n in new if n in old and old[n].spec != new[n].spec],
    )


def _manifests(ctx: Context) -> Iterable[tuple[FileChange, DepDiff]]:
    for fc in ctx.files:
        if fc.binary or not ctx.paths.is_manifest(fc.path):
            continue
        yield fc, diff_deps(fc)


def _label(dep: Dep) -> str:
    return f"{dep.name} {dep.spec}".strip()


def _operator(spec: str) -> str:
    return re.match(r"[^\d]*", spec.strip().lstrip("v")).group(0)


def _kind_of_jump(old: Dep, new: Dep) -> str | None:
    a, b = old.version, new.version
    if a is None or b is None:
        return None
    if b < a and _operator(old.spec) == _operator(new.spec):
        return "downgrade"
    if a[0] != b[0] or (a[0] == 0 and b[0] == 0 and a[1] != b[1]):
        return "major"
    return None


@register
class DependenciesChanged(Rule):
    info = DEP001

    def check(self, ctx: Context) -> Iterable[Finding]:
        many = int(ctx.options(self.info)["many"])
        for fc, diff in _manifests(ctx):
            if not diff:
                continue
            parts = []
            if diff.added:
                parts.append("added " + join_names([_label(d) for d in diff.added]))
            if diff.removed:
                parts.append("removed " + join_names([d.name for d in diff.removed]))
            if diff.changed:
                parts.append(
                    "changed "
                    + join_names(
                        [
                            f"{o.name} {o.spec or '(any)'} to {n.spec or '(any)'}"
                            for o, n in diff.changed
                        ]
                    )
                )
            ev = [evidence(fc.path, d.line, d.text, "old") for d in diff.removed]
            ev += [
                evidence(fc.path, n.line, n.text)
                for n in [*diff.added, *(n for _, n in diff.changed)]
            ]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {'; '.join(parts)}.",
                paths=[fc.path],
                evidence=ev,
                bump=1 if diff.count >= many else 0,
            )


@register
class MajorVersionChange(Rule):
    info = DEP002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc, diff in _manifests(ctx):
            jumps = [(o, n, _kind_of_jump(o, n)) for o, n in diff.changed]
            jumps = [(o, n, k) for o, n, k in jumps if k]
            if not jumps:
                continue
            bits = [
                f"{o.name} {o.spec} to {n.spec}" + (" (downgrade)" if k == "downgrade" else "")
                for o, n, k in jumps[:4]
            ]
            more = len(jumps) - len(bits)
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {'; '.join(bits)}"
                + (f"; and {more} more." if more > 0 else "."),
                paths=[fc.path],
                evidence=[evidence(fc.path, n.line, n.text) for _, n, _ in jumps],
                bump=1 if len(jumps) >= 3 else 0,
            )


@register
class PinLoosened(Rule):
    info = DEP003

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc, diff in _manifests(ctx):
            loosened = [(o, n) for o, n in diff.changed if o.pinned and not n.pinned]
            if not loosened:
                continue
            bits = [f"{o.name} {o.spec} to {n.spec or '(any version)'}" for o, n in loosened[:4]]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {'; '.join(bits)}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, n.line, n.text) for _, n in loosened],
            )


@register
class LockfileBehind(Rule):
    info = DEP004

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc, diff in _manifests(ctx):
            if not diff:
                continue
            base = PurePosixPath(fc.path)
            candidates = LOCKS.get(base.name.lower(), ())
            existing = [str(base.parent / c) if str(base.parent) != "." else c for c in candidates]
            present = [c for c in existing if c in ctx.changes.repo_files]
            if not present or any(c in ctx.changed_paths for c in present):
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} changed {plural(diff.count, 'dependency', 'dependencies')} "
                f"but {present[0]} was not updated.",
                paths=[fc.path, present[0]],
                evidence=[
                    evidence(fc.path, d.line, d.text)
                    for d in [*diff.added, *(n for _, n in diff.changed)]
                ],
            )
