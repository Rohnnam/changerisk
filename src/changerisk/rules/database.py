"""DB001-DB003: schema migrations."""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import PurePosixPath

from ..models import ADDED, DELETED, Finding, Severity
from ..paths import is_comment
from .base import Context, Rule, RuleInfo, evidence, plural, register

DB001 = RuleInfo(
    id="DB001",
    name="Schema migration added",
    category="database",
    severity=Severity.MEDIUM,
    summary="A new migration file was added.",
    why=(
        "A migration changes shared state that cannot be rolled back by redeploying the previous "
        "version, and it runs against data volumes the test database never had."
    ),
    tests=(
        "Run {path} against a copy of production-sized data and time it",
        "Run the previous application version against the migrated schema (rolling deploys do this)",
        "Write down and rehearse the rollback",
    ),
)
DB002 = RuleInfo(
    id="DB002",
    name="Destructive schema statement",
    category="database",
    severity=Severity.HIGH,
    summary="Drops, truncates, unqualified deletes, renames, type changes, or NOT NULL without a default.",
    why=(
        "These statements lose data, lock large tables, or break the version of the application "
        "that is still running during the deploy."
    ),
    tests=(
        "Take a backup and restore it into a scratch database before running {path}",
        "Check that no running code still reads the dropped or renamed column",
        "Use expand-and-contract: add the new shape, migrate readers, then remove the old one",
    ),
)
DB003 = RuleInfo(
    id="DB003",
    name="Applied migration edited",
    category="database",
    severity=Severity.HIGH,
    summary="A migration that already existed was modified, renamed or deleted.",
    why=(
        "Databases that already ran the old version will not run it again, so environments drift "
        "apart silently and the history no longer describes any real database."
    ),
    tests=(
        "Put the change in a new migration instead",
        "Compare the schema of a freshly migrated database with one migrated before this change",
    ),
)

# (pattern, severity bump relative to HIGH, short description)
_STATEMENTS = (
    (re.compile(r"(?i)\bDROP\s+(?:DATABASE|SCHEMA)\b"), 1, "drops a database or schema"),
    (re.compile(r"(?i)\bDROP\s+(?:TABLE|COLUMN|INDEX|CONSTRAINT|VIEW)\b"), 0, "drops a table, column or index"),
    (re.compile(r"(?i)\bTRUNCATE\b"), 0, "truncates a table"),
    (re.compile(r"(?i)\bDELETE\s+FROM\s+[\w\".`]+\s*;"), 0, "deletes every row of a table"),
    (re.compile(r"(?i)\bALTER\s+TABLE\b.*\bDROP\b"), 0, "drops a column or constraint"),
    (re.compile(r"(?i)\bRENAME\s+(?:COLUMN|TO)\b"), -1, "renames a column or table"),
    (re.compile(r"(?i)\bALTER\s+COLUMN\b.*\b(?:SET\s+DATA\s+)?TYPE\b"), -1, "changes a column type"),
    (re.compile(r"(?i)\bADD\s+COLUMN\b(?=[^;]*\bNOT\s+NULL\b)(?![^;]*\bDEFAULT\b)"), -1, "adds a NOT NULL column with no default"),
    (re.compile(r"\bop\.(?:drop_(?:column|table|index|constraint)|alter_column)\("), 0, "drops or alters a column (alembic)"),
    (re.compile(r"\b(?:remove_column|drop_table|rename_column|rename_table|change_column)\b"), 0, "removes or renames schema (rails)"),
    (re.compile(r"\bmigrations\.(?:RemoveField|DeleteModel|RenameField|RenameModel|AlterField)\("), 0, "removes or alters a field (django)"),
)  # fmt: skip

_SNAPSHOTS = {"schema.rb", "structure.sql", "schema.prisma"}


def _is_sql_like(ctx: Context, path: str) -> bool:
    return ctx.paths.is_migration(path) or PurePosixPath(path).suffix.lower() == ".sql"


@register
class MigrationAdded(Rule):
    info = DB001

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.status != ADDED or not ctx.paths.is_migration(fc.path) or fc.binary:
                continue
            if PurePosixPath(fc.path).name.lower() in _SNAPSHOTS:
                continue
            ev = [
                evidence(fc.path, ln.new_no, ln.text)
                for ln in fc.added_lines()
                if re.match(
                    r"\s*(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|TRUNCATE|op\.|migrations\.)",
                    ln.text,
                    re.I,
                )
            ]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} adds a migration ({plural(fc.additions, 'line')}).",
                paths=[fc.path],
                evidence=ev,
            )


@register
class DestructiveStatement(Rule):
    info = DB002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or fc.status == DELETED or not _is_sql_like(ctx, fc.path):
                continue
            lang = ctx.paths.language(fc.path)
            hits: list[tuple[int, str, str, int]] = []
            for ln in ctx.added(fc, self.info.id):
                if is_comment(ln.text, lang) or ln.text.lstrip().startswith(("--", "#")):
                    continue
                for pattern, bump, label in _STATEMENTS:
                    if pattern.search(ln.text):
                        hits.append((ln.new_no or 0, ln.text, label, bump))
                        break
            if not hits:
                continue
            labels = list(dict.fromkeys(label for _, _, label, _ in hits))
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} {'; '.join(labels[:3])}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, no, text) for no, text, _, _ in hits],
                bump=max(b for *_, b in hits),
            )


@register
class AppliedMigrationEdited(Rule):
    info = DB003

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.status == ADDED or fc.binary or not ctx.paths.is_migration(fc.path):
                continue
            if PurePosixPath(fc.path).name.lower() in _SNAPSHOTS or not fc.changed_lines:
                continue
            verb = "deleted" if fc.status == DELETED else "edited"
            ev = [
                evidence(fc.path, ln.new_no, ln.text) for ln in fc.added_lines() if ln.text.strip()
            ] or [
                evidence(fc.path, ln.old_no, ln.text, "old")
                for ln in fc.removed_lines()
                if ln.text.strip()
            ]
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} was {verb} after it already existed. Databases that ran the old "
                "version will not run this one.",
                paths=[fc.path],
                evidence=ev,
            )
