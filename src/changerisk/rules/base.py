"""Rule plumbing: metadata, the registry, and the context handed to every rule."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..config import Config
from ..history import History
from ..models import ChangeSet, Evidence, FileChange, Finding, Line, Severity
from ..paths import matches_any

CATEGORIES = {
    "config": "Configuration",
    "tests": "Tests",
    "deps": "Dependencies",
    "security": "Security",
    "pipeline": "Pipeline",
    "database": "Database",
    "size": "Size and spread",
    "history": "History",
    "interfaces": "Interfaces",
    "code": "Code patterns",
}

MAX_EVIDENCE = 6
MAX_TEXT = 160


@dataclass(frozen=True)
class RuleInfo:
    id: str
    name: str
    category: str
    severity: Severity
    summary: str  # what it looks for, one line
    why: str  # why that is risky
    tests: tuple[str, ...]  # what to test because of it
    options: dict[str, Any] = field(default_factory=dict)  # option name -> default


class Rule:
    info: ClassVar[RuleInfo]

    def check(self, ctx: Context) -> Iterable[Finding]:
        raise NotImplementedError


_REGISTRY: dict[str, Rule] = {}


def register(cls: type[Rule]) -> type[Rule]:
    rid = cls.info.id
    if rid in _REGISTRY:
        raise RuntimeError(f"rule id {rid} registered twice")
    if cls.info.category not in CATEGORIES:
        raise RuntimeError(f"{rid} uses unknown category {cls.info.category!r}")
    _REGISTRY[rid] = cls()
    return cls


def all_rules() -> list[Rule]:
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def get_rule(rule_id: str) -> Rule | None:
    return _REGISTRY.get(rule_id)


def option_defaults() -> dict[str, dict[str, Any]]:
    return {rid: dict(rule.info.options) for rid, rule in _REGISTRY.items()}


_IGNORE = re.compile(
    r"changerisk:\s*ignore(?:\[([\w, ]+)\]|\s+([A-Z]{2,4}\d{3}(?:[, ]+[A-Z]{2,4}\d{3})*))?"
)


def suppressed(text: str, rule_id: str) -> bool:
    """True when the line carries `changerisk: ignore` for this rule (or for every rule)."""
    m = _IGNORE.search(text)
    if not m:
        return False
    listed = m.group(1) or m.group(2)
    if not listed:
        return True
    return rule_id in {part.strip() for part in re.split(r"[,\s]+", listed) if part.strip()}


def trim(text: str, limit: int = MAX_TEXT) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def evidence(path: str, line: int | None, text: str, side: str = "new") -> Evidence:
    return Evidence(path=path, line=line, text=trim(text), side=side)


class _Fill(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def fill(text: str, paths: list[str]) -> str:
    """Substitute {path} and {paths} in a test suggestion."""
    values = _Fill(
        path=paths[0] if paths else "the changed files",
        paths=join_names(paths, 3) if paths else "the changed files",
    )
    try:
        return text.format_map(values)
    except (ValueError, IndexError):
        return text


class Context:
    """What a rule gets to look at: the change, the settings, and optional history."""

    def __init__(self, changes: ChangeSet, config: Config, history: History | None = None) -> None:
        self.changes = changes
        self.config = config
        self.history = history
        self.paths = config.classifier()
        self.files: list[FileChange] = [
            f for f in changes.files if not matches_any(f.path, config.ignore)
        ]
        self.ignored_count = len(changes.files) - len(self.files)
        self.changed_paths = {f.path for f in self.files}

    def options(self, info: RuleInfo) -> dict[str, Any]:
        return {**info.options, **self.config.rule(info.id).options}

    def severity(self, info: RuleInfo, bump: int = 0) -> Severity:
        base = self.config.rule(info.id).severity or info.severity
        return base.shifted(bump) if bump else base

    def added(self, fc: FileChange, rule_id: str) -> Iterator[Line]:
        """Added lines, minus any the author marked with an inline ignore."""
        for line in fc.added_lines():
            if not suppressed(line.text, rule_id):
                yield line

    def finding(
        self,
        info: RuleInfo,
        *,
        detail: str,
        paths: Iterable[str],
        evidence: Iterable[Evidence] = (),
        bump: int = 0,
        title: str | None = None,
        extra_tests: Iterable[str] = (),
        tests: Iterable[str] | None = None,
        scope: str = "file",
    ) -> Finding:
        shown = list(evidence)[:MAX_EVIDENCE]
        path_list = list(dict.fromkeys(paths))
        return Finding(
            rule_id=info.id,
            category=info.category,
            title=title or info.name,
            severity=self.severity(info, bump),
            detail=detail,
            paths=path_list,
            evidence=shown,
            why=info.why,
            scope=scope,
            test_focus=[
                fill(x, path_list)
                for x in (*(info.tests if tests is None else tests), *extra_tests)
            ],
        )


def plural(n: int, noun: str, many: str | None = None) -> str:
    return f"{n} {noun if n == 1 else (many or noun + 's')}"


def join_names(names: list[str], limit: int = 3) -> str:
    """'a, b and c' / 'a, b, c and 2 more'."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    shown = names[:limit]
    rest = len(names) - len(shown)
    if rest:
        return ", ".join(shown) + f" and {rest} more"
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def describe_rules(cfg: Config) -> list[dict[str, Any]]:
    """Every rule with the severity and options in effect, for the dashboard's rule list."""
    out = []
    for rule in all_rules():
        info = rule.info
        settings = cfg.rule(info.id)
        out.append(
            {
                "id": info.id,
                "name": info.name,
                "category": info.category,
                "category_label": CATEGORIES[info.category],
                "severity": (settings.severity or info.severity).label,
                "enabled": settings.enabled,
                "summary": info.summary,
                "why": info.why,
                "tests": list(info.tests),
                "options": {**info.options, **settings.options},
            }
        )
    return out
