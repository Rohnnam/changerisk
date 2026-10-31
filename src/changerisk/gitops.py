"""Everything that talks to the git executable."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from .diffparse import parse_diff
from .models import ADDED, ChangeSet, CommitInfo

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
DEFAULT_BASE_CANDIDATES = ("origin/main", "origin/master", "main", "master", "develop")
MAX_DIFF_BYTES = 30 * 1024 * 1024
MAX_UNTRACKED = 200

_REF_OK = re.compile(r"^[\w./@^~{}+:#=-]{1,200}$")


class GitError(RuntimeError):
    """A git command failed or the repository is not in a usable state."""


def _env() -> dict[str, str]:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    env["GIT_PAGER"] = "cat"
    env["LC_ALL"] = "C"
    return env


def run_git(
    repo: Path | str,
    *args: str,
    check: bool = True,
    stdin: str | None = None,
    timeout: float = 120,
    ok_codes: tuple[int, ...] = (0,),
) -> str:
    """Run git with an argument list (never through a shell) and return stdout as text."""
    cmd = ["git", "-c", "core.quotepath=false", "-c", "color.ui=never", *args]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(repo),
            input=stdin.encode("utf-8") if stdin is not None else None,
            capture_output=True,
            timeout=timeout,
            env=_env(),
            check=False,
        )
    except FileNotFoundError:
        raise GitError("git was not found on PATH") from None
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out after {timeout:.0f}s") from None
    if check and proc.returncode not in ok_codes:
        message = proc.stderr.decode("utf-8", errors="replace").strip()
        if "dubious ownership" in message:
            message += (
                "\nTell git the checkout is safe: git config --global --add safe.directory <path>"
            )
        raise GitError(message or f"git {args[0]} exited with {proc.returncode}")
    return proc.stdout.decode("utf-8", errors="replace")


def repo_root(start: Path | str = ".") -> Path:
    start = Path(start)
    if not start.exists():
        raise GitError(f"{start} does not exist")
    try:
        out = run_git(start, "rev-parse", "--show-toplevel").strip()
    except GitError as exc:
        text = str(exc)
        if "not a git repository" in text:
            raise GitError(f"{start.resolve()} is not inside a git repository") from None
        raise
    return Path(out)


def validate_ref(ref: str) -> str:
    """Reject anything that could be read as an option or is plainly not a revision."""
    if not ref or ref.startswith("-") or not _REF_OK.match(ref):
        raise GitError(f"{ref!r} is not a usable git revision")
    return ref


def resolve(repo: Path | str, ref: str) -> str:
    validate_ref(ref)
    out = run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    sha = out.strip()
    if not sha:
        raise GitError(f"unknown revision {ref!r}; check the name or fetch more history")
    return sha


def has_commits(repo: Path | str) -> bool:
    return bool(run_git(repo, "rev-parse", "--verify", "--quiet", "HEAD", check=False).strip())


def merge_base(repo: Path | str, a: str, b: str) -> str | None:
    out = run_git(repo, "merge-base", a, b, check=False).strip()
    return out or None


def is_shallow(repo: Path | str) -> bool:
    return run_git(repo, "rev-parse", "--is-shallow-repository", check=False).strip() == "true"


def current_branch(repo: Path | str) -> str | None:
    out = run_git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).strip()
    return out or None


def default_base(repo: Path | str) -> str | None:
    """Best guess at the branch a change will be merged into."""
    head_ref = run_git(
        repo, "symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD", check=False
    ).strip()
    candidates = ([head_ref] if head_ref else []) + list(DEFAULT_BASE_CANDIDATES)
    for ref in candidates:
        if run_git(repo, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False):
            return ref
    return None


def repo_name(repo: Path | str) -> str:
    url = run_git(repo, "config", "--get", "remote.origin.url", check=False).strip()
    if url:
        tail = re.split(r"[/:]", url.rstrip("/"))[-1]
        return tail.removesuffix(".git") or Path(repo).name
    return Path(repo).name


def tracked_files(repo: Path | str, ref: str) -> frozenset[str]:
    out = run_git(repo, "ls-tree", "-r", "--name-only", "-z", ref)
    return frozenset(p for p in out.split("\0") if p)


def commits_between(
    repo: Path | str, base_sha: str, head_sha: str, limit: int = 500
) -> list[CommitInfo]:
    fmt = "%H%x1f%an%x1f%aI%x1f%s%x1e"
    out = run_git(
        repo,
        "log",
        "--no-color",
        f"--max-count={limit}",
        f"--format={fmt}",
        f"{base_sha}..{head_sha}",
    )
    commits = []
    for chunk in out.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk:
            continue
        sha, author, date, subject = (chunk.split("\x1f") + ["", "", "", ""])[:4]
        commits.append(CommitInfo(sha=sha, author=author, date=date, subject=subject))
    return commits


_DIFF_FLAGS = (
    "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", "-U3",
    "--src-prefix=a/", "--dst-prefix=b/",
)  # fmt: skip


def _diff(repo: Path | str, *extra: str, ok_codes: tuple[int, ...] = (0,)) -> tuple[str, bool]:
    text = run_git(repo, *_DIFF_FLAGS, *extra, ok_codes=ok_codes)
    if len(text) > MAX_DIFF_BYTES:
        cut = text.rfind("\ndiff --git ", 0, MAX_DIFF_BYTES)
        return text[: cut if cut > 0 else MAX_DIFF_BYTES], True
    return text, False


def _untracked_diff(repo: Path | str) -> str:
    listing = run_git(repo, "ls-files", "--others", "--exclude-standard", "-z")
    names = [n for n in listing.split("\0") if n][:MAX_UNTRACKED]
    chunks = []
    for name in names:
        chunks.append(
            run_git(
                repo, "diff", "--no-color", "--no-index", "--no-ext-diff", "--src-prefix=a/",
                "--dst-prefix=b/", "--", "/dev/null", name, ok_codes=(0, 1),
            )
        )  # fmt: skip
    return "".join(chunks)


def load_changes(
    repo: Path | str,
    base: str | None = None,
    head: str | None = None,
    *,
    mode: str = "range",
) -> ChangeSet:
    """Build a ChangeSet for a revision range, the index, or the working tree.

    In range mode this is the diff a pull request shows: from the merge base of `base` and
    `head` up to `head`.
    """
    repo = Path(repo)
    name = repo_name(repo)

    if mode == "range":
        head = head or "HEAD"
        if base is None:
            base = default_base(repo)
            if base is None:
                raise GitError(
                    "could not find a base branch (looked for origin/main, main, master); "
                    "pass --base explicitly"
                )
        base_sha, head_sha = resolve(repo, base), resolve(repo, head)
        mb = merge_base(repo, base_sha, head_sha)
        if mb is None:
            raise GitError(
                f"{base} and {head} share no history. In CI, check out with fetch-depth: 0."
            )
        text, truncated = _diff(repo, f"{mb}", head_sha)
        files = parse_diff(text)
        commits = commits_between(repo, mb, head_sha)
        listing = tracked_files(repo, head_sha)
        return ChangeSet(
            files=files, base=base, head=head, base_sha=base_sha, head_sha=head_sha,
            merge_base=mb, mode="range", commits=commits, repo_files=listing,
            repo_name=name, truncated=truncated,
        )  # fmt: skip

    if mode not in ("staged", "worktree"):
        raise GitError(f"unknown mode {mode!r}")

    if has_commits(repo):
        head_sha = resolve(repo, "HEAD")
        against = head_sha
        listing = tracked_files(repo, head_sha)
    else:
        head_sha, against, listing = None, EMPTY_TREE, frozenset()

    if mode == "staged":
        text, truncated = _diff(repo, "--cached", against)
    else:
        text, truncated = _diff(repo, against)
        extra = _untracked_diff(repo)
        text += extra
    files = parse_diff(text)
    if mode == "worktree":
        # Untracked files are not in the index yet, so they were never in `listing`.
        listing = listing | frozenset(f.path for f in files if f.status == ADDED)
    label = "staged changes" if mode == "staged" else "working tree"
    return ChangeSet(
        files=files, base="HEAD" if head_sha else "(empty)", head=label, base_sha=head_sha,
        head_sha=None, merge_base=head_sha, mode=mode, commits=[], repo_files=listing,
        repo_name=name, truncated=truncated,
    )  # fmt: skip
