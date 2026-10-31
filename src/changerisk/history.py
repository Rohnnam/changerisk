"""History signals: how often, and how badly, the files in a change have been touched lately."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .gitops import GitError, run_git

FIX_SUBJECT = re.compile(
    r"(?i)\b(fix(?:es|ed|ing)?|bug(?:fix)?|hotfix|regression|crash(?:es)?|broken|incident|patch)\b"
)
MAX_COMMITS = 4000


@dataclass
class FileHistory:
    commits: int = 0
    fixes: int = 0
    authors: set[str] = field(default_factory=set)

    @property
    def fix_ratio(self) -> float:
        return self.fixes / self.commits if self.commits else 0.0


@dataclass
class History:
    days: int
    window_start: str
    files: dict[str, FileHistory]

    def get(self, path: str) -> FileHistory | None:
        return self.files.get(path)


def collect(repo, paths: list[str], since_ref: str, days: int = 90) -> History | None:
    """Look back `days` from `since_ref`'s commit date, so results do not depend on today's date.

    Returns None when there is nothing to look at (no paths) or the history is unreachable.
    """
    if not paths:
        return None
    try:
        stamp = run_git(repo, "show", "-s", "--format=%cI", since_ref).strip()
        anchor = datetime.fromisoformat(stamp)
    except (GitError, ValueError):
        return None
    start = (anchor - timedelta(days=days)).isoformat()

    # Paths go over stdin: a big change would overflow the command line on Windows.
    stdin = f"{since_ref}\n--\n" + "\n".join(paths) + "\n"
    fmt = "\x1e%H\x1f%an\x1f%s"
    try:
        out = run_git(
            repo, "log", "--no-color", "--no-merges", "--no-renames", f"--since={start}",
            f"--max-count={MAX_COMMITS}", f"--format={fmt}", "--name-only", "--stdin",
            stdin=stdin,
        )  # fmt: skip
    except GitError:
        return None

    files: dict[str, FileHistory] = {}
    for block in out.split("\x1e"):
        block = block.strip("\n")
        if not block:
            continue
        head, _, names = block.partition("\n")
        _sha, author, subject = (head.split("\x1f") + ["", "", ""])[:3]
        is_fix = bool(FIX_SUBJECT.search(subject))
        for name in names.split("\n"):
            name = name.strip()
            if not name:
                continue
            fh = files.setdefault(name, FileHistory())
            fh.commits += 1
            fh.authors.add(author)
            if is_fix:
                fh.fixes += 1
    return History(days=days, window_start=start, files=files)
