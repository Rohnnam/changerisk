"""Data shapes shared by the whole pipeline: the parsed change, findings, and the report."""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

SCHEMA = "changerisk.report/1"

# File statuses as git reports them, spelled out.
ADDED = "added"
MODIFIED = "modified"
DELETED = "deleted"
RENAMED = "renamed"
COPIED = "copied"
TYPECHANGE = "typechange"


_FULL_SHA = re.compile(r"[0-9a-f]{40}")


def display_ref(ref: str) -> str:
    """A ref as a person would write it: full commit ids are cut to eight characters."""
    return ref[:8] if _FULL_SHA.fullmatch(ref) else ref


class Severity(IntEnum):
    INFO = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    CRITICAL = 4

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str | Severity) -> Severity:
        if isinstance(value, Severity):
            return value
        try:
            return cls[str(value).strip().upper()]
        except KeyError:
            names = ", ".join(s.label for s in cls)
            raise ValueError(f"unknown severity {value!r} (use one of: {names})") from None

    def shifted(self, steps: int) -> Severity:
        """Move up or down the scale without leaving LOW..CRITICAL."""
        return Severity(max(Severity.LOW, min(Severity.CRITICAL, self + steps)))


class Level(IntEnum):
    LOW = 0
    MODERATE = 1
    HIGH = 2
    CRITICAL = 3

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: str | Level) -> Level:
        if isinstance(value, Level):
            return value
        try:
            return cls[str(value).strip().upper()]
        except KeyError:
            names = ", ".join(lv.label for lv in cls)
            raise ValueError(f"unknown level {value!r} (use one of: {names})") from None


# ---------------------------------------------------------------------------
# The parsed change
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Line:
    kind: str  # "+", "-" or " "
    old_no: int | None
    new_no: int | None
    text: str


@dataclass(slots=True)
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str = ""
    lines: list[Line] = field(default_factory=list)


@dataclass
class FileChange:
    path: str
    status: str = MODIFIED
    old_path: str | None = None
    binary: bool = False
    similarity: int | None = None
    mode_change: tuple[str, str] | None = None
    hunks: list[Hunk] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0

    @property
    def changed_lines(self) -> int:
        return self.additions + self.deletions

    def added_lines(self) -> Iterator[Line]:
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "+":
                    yield line

    def removed_lines(self) -> Iterator[Line]:
        for hunk in self.hunks:
            for line in hunk.lines:
                if line.kind == "-":
                    yield line

    def count_lines(self) -> None:
        self.additions = sum(1 for _ in self.added_lines())
        self.deletions = sum(1 for _ in self.removed_lines())


@dataclass(frozen=True, slots=True)
class CommitInfo:
    sha: str
    author: str
    date: str
    subject: str


@dataclass
class ChangeSet:
    files: list[FileChange]
    base: str = ""
    head: str = ""
    base_sha: str | None = None
    head_sha: str | None = None
    merge_base: str | None = None
    mode: str = "range"
    commits: list[CommitInfo] = field(default_factory=list)
    repo_files: frozenset[str] = frozenset()
    repo_name: str = ""
    truncated: bool = False
    source: dict[str, Any] | None = None  # set for pasted diffs and GitHub pull requests

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)

    def paths(self) -> set[str]:
        return {f.path for f in self.files}


# ---------------------------------------------------------------------------
# Findings and the report
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Evidence:
    path: str
    line: int | None
    text: str
    side: str = "new"  # which side of the diff `line` refers to: "new" or "old"

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "line": self.line, "text": self.text, "side": self.side}


@dataclass
class Finding:
    rule_id: str
    category: str
    title: str
    severity: Severity
    detail: str
    paths: list[str]
    evidence: list[Evidence] = field(default_factory=list)
    why: str = ""
    test_focus: list[str] = field(default_factory=list)
    points: float = 0.0
    id: str = ""
    scope: str = "file"  # "change" for findings about the whole change, not one file

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "rule": self.rule_id,
            "scope": self.scope,
            "category": self.category,
            "title": self.title,
            "severity": self.severity.label,
            "points": round(self.points, 1),
            "detail": self.detail,
            "paths": self.paths,
            "evidence": [e.to_dict() for e in self.evidence],
            "why": self.why,
            "test_focus": self.test_focus,
        }


@dataclass
class PlanStep:
    text: str
    priority: int  # 1 = do before merging, 2 = should do, 3 = nice to have
    rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "priority": self.priority, "rules": self.rules}


@dataclass
class FileReport:
    path: str
    status: str
    additions: int
    deletions: int
    old_path: str | None = None
    binary: bool = False
    points: float = 0.0
    findings: list[str] = field(default_factory=list)
    hunks: list[dict[str, Any]] | None = None
    truncated: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "path": self.path,
            "old_path": self.old_path,
            "status": self.status,
            "additions": self.additions,
            "deletions": self.deletions,
            "binary": self.binary,
            "points": round(self.points, 1),
            "findings": self.findings,
        }
        if self.hunks is not None:
            out["hunks"] = self.hunks
            out["truncated"] = self.truncated
        return out


@dataclass
class RiskReport:
    repo: str
    base: str
    head: str
    mode: str
    base_sha: str | None
    head_sha: str | None
    merge_base: str | None
    generated_at: str
    tool_version: str
    additions: int
    deletions: int
    commit_count: int
    points: float
    score: int
    level: Level
    floor_note: str | None
    verdict: str
    recommendation: str
    fail_on: str
    gate_failed: bool
    gate_reason: str
    findings: list[Finding]
    categories: list[dict[str, Any]]
    test_plan: list[PlanStep]
    files: list[FileReport]
    commits: list[CommitInfo]
    notes: list[str] = field(default_factory=list)
    id: str | None = None
    source: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "id": self.id,
            "tool_version": self.tool_version,
            "generated_at": self.generated_at,
            "repo": self.repo,
            "range": {
                "mode": self.mode,
                "base": self.base,
                "head": self.head,
                "base_sha": self.base_sha,
                "head_sha": self.head_sha,
                "merge_base": self.merge_base,
            },
            "stats": {
                "files": len(self.files),
                "additions": self.additions,
                "deletions": self.deletions,
                "commits": self.commit_count,
            },
            "score": self.score,
            "points": round(self.points, 1),
            "level": self.level.label,
            "floor_note": self.floor_note,
            "verdict": self.verdict,
            "recommendation": self.recommendation,
            "gate": {
                "fail_on": self.fail_on,
                "failed": self.gate_failed,
                "reason": self.gate_reason,
            },
            "findings": [f.to_dict() for f in self.findings],
            "categories": self.categories,
            "test_plan": [t.to_dict() for t in self.test_plan],
            "files": [f.to_dict() for f in self.files],
            "commits": [
                {"sha": c.sha, "author": c.author, "date": c.date, "subject": c.subject}
                for c in self.commits
            ],
            "notes": self.notes,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RiskReport:
        """Rebuild a report from its JSON form (what the store keeps)."""
        rng, stats, gate = data["range"], data["stats"], data["gate"]
        findings = [
            Finding(
                rule_id=f["rule"],
                category=f["category"],
                title=f["title"],
                severity=Severity.parse(f["severity"]),
                detail=f["detail"],
                paths=list(f["paths"]),
                evidence=[
                    Evidence(e["path"], e.get("line"), e["text"], e.get("side", "new"))
                    for e in f["evidence"]
                ],
                why=f.get("why", ""),
                test_focus=list(f.get("test_focus", [])),
                points=float(f.get("points", 0)),
                id=f.get("id", ""),
                scope=f.get("scope", "file"),
            )
            for f in data["findings"]
        ]
        files = [
            FileReport(
                path=f["path"],
                status=f["status"],
                additions=f["additions"],
                deletions=f["deletions"],
                old_path=f.get("old_path"),
                binary=f.get("binary", False),
                points=float(f.get("points", 0)),
                findings=list(f.get("findings", [])),
                hunks=f.get("hunks"),
                truncated=f.get("truncated", False),
            )
            for f in data["files"]
        ]
        return cls(
            repo=data["repo"],
            base=rng["base"],
            head=rng["head"],
            mode=rng["mode"],
            base_sha=rng.get("base_sha"),
            head_sha=rng.get("head_sha"),
            merge_base=rng.get("merge_base"),
            generated_at=data["generated_at"],
            tool_version=data["tool_version"],
            additions=stats["additions"],
            deletions=stats["deletions"],
            commit_count=stats["commits"],
            points=float(data["points"]),
            score=data["score"],
            level=Level.parse(data["level"]),
            floor_note=data.get("floor_note"),
            verdict=data["verdict"],
            recommendation=data["recommendation"],
            fail_on=gate["fail_on"],
            gate_failed=gate["failed"],
            gate_reason=gate["reason"],
            findings=findings,
            categories=list(data["categories"]),
            test_plan=[
                PlanStep(t["text"], t["priority"], list(t.get("rules", [])))
                for t in data["test_plan"]
            ],
            files=files,
            commits=[
                CommitInfo(c["sha"], c["author"], c["date"], c["subject"]) for c in data["commits"]
            ],
            notes=list(data.get("notes", [])),
            id=data.get("id"),
            source=data.get("source"),
        )
