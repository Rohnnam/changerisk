"""Build ChangeSets from before/after text so rule tests do not need a git repository."""

from __future__ import annotations

import difflib
from collections.abc import Iterable

from changerisk.config import Config
from changerisk.diffparse import parse_diff
from changerisk.history import History
from changerisk.models import ChangeSet, Finding
from changerisk.rules.base import Context, get_rule

Before = str | None
After = str | None


def git_diff(path: str, old: Before, new: After, old_path: str | None = None) -> str:
    a = (old or "").splitlines()
    b = (new or "").splitlines()
    head = [f"diff --git a/{old_path or path} b/{path}"]
    if old is None:
        head.append("new file mode 100644")
    elif new is None:
        head.append("deleted file mode 100644")
    elif old_path:
        head += ["similarity index 90%", f"rename from {old_path}", f"rename to {path}"]
    head.append("index 1111111..2222222 100644")
    body = list(
        difflib.unified_diff(
            a, b, fromfile="/dev/null" if old is None else f"a/{old_path or path}",
            tofile="/dev/null" if new is None else f"b/{path}", lineterm="", n=3,
        )
    )  # fmt: skip
    if not body:
        return "\n".join(head) + "\n"
    return "\n".join([*head, *body]) + "\n"


def change(
    files: dict[str, tuple[Before, After]],
    *,
    repo_files: Iterable[str] = (),
    commits=(),
) -> ChangeSet:
    text = "".join(git_diff(path, old, new) for path, (old, new) in files.items())
    parsed = parse_diff(text)
    present = {p for p, (_, new) in files.items() if new is not None}
    return ChangeSet(
        files=parsed, base="main", head="topic", base_sha="a" * 40, head_sha="b" * 40,
        merge_base="a" * 40, commits=list(commits),
        repo_files=frozenset(present | set(repo_files)), repo_name="demo",
    )  # fmt: skip


def lines(*items: str) -> str:
    return "\n".join(items) + "\n"


def run_rule(
    rule_id: str,
    changes: ChangeSet,
    config: Config | None = None,
    history: History | None = None,
) -> list[Finding]:
    from changerisk.rules import load_all

    load_all()
    rule = get_rule(rule_id)
    assert rule is not None, rule_id
    ctx = Context(changes, config or Config(), history)
    return list(rule.check(ctx))
