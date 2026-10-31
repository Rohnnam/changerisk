"""Getting a change from somewhere other than a local repository.

Two sources: a unified diff someone pasted, and a public GitHub pull request. This is the input
side of the hosted dashboard, so it treats everything as untrusted: strict URL parsing, a fixed
list of hosts it will talk to, size and line-length caps, and error messages written for the person
who typed the input.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlsplit

from .config import CONFIG_NAMES, Config, ConfigError, parse_config
from .diffparse import parse_diff
from .gitops import GitError, validate_ref
from .models import ChangeSet, CommitInfo
from .paths import Classifier

API_HOST = "api.github.com"
RAW_HOST = "raw.githubusercontent.com"
ALLOWED_HOSTS = {API_HOST, RAW_HOST}

MAX_DIFF_BYTES = int(os.environ.get("CHANGERISK_MAX_DIFF_KB", "2048")) * 1024
MAX_LINE_CHARS = 2000  # longer lines are cut: they only slow the pattern rules down
MAX_FILES = 1500
MAX_CONFIG_BYTES = 64 * 1024
TIMEOUT = 15

_OWNER = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
_REPO = r"[A-Za-z0-9._-]{1,100}"
_PR_URL = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_OWNER})/({_REPO})/pull/(\d{{1,7}})(?:[/?#].*)?$"
)
_PR_SHORT = re.compile(rf"^({_OWNER})/({_REPO})#(\d{{1,7}})$")
_COMPARE_URL = re.compile(
    rf"^(?:https?://)?(?:www\.)?github\.com/({_OWNER})/({_REPO})/compare/([^\s?#]{{1,200}})\.\.\.([^\s?#]{{1,200}})$"
)


class SourceError(ValueError):
    """The input could not be turned into a change. The message is meant to be shown as is."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class PullRef:
    owner: str
    repo: str
    number: int

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


@dataclass(frozen=True)
class CompareRef:
    owner: str
    repo: str
    base: str
    head: str

    @property
    def label(self) -> str:
        return f"{self.owner}/{self.repo}@{self.base}...{self.head}"


def parse_source(text: str) -> PullRef | CompareRef:
    text = (text or "").strip()
    if not text or len(text) > 400:
        raise SourceError(_HINT)
    m = _PR_URL.match(text) or _PR_SHORT.match(text)
    if m:
        return PullRef(m.group(1), m.group(2), int(m.group(3)))
    m = _COMPARE_URL.match(text)
    if m:
        base, head = m.group(3), m.group(4)
        try:
            validate_ref(base)
            validate_ref(head)
        except GitError:
            raise SourceError("Those branch names in the compare link are not usable.") from None
        return CompareRef(m.group(1), m.group(2), base, head)
    raise SourceError(_HINT)


_HINT = (
    "Enter a public GitHub pull request, such as https://github.com/owner/repo/pull/123 "
    "or owner/repo#123. A compare link (github.com/owner/repo/compare/main...branch) also works."
)


# --- diffs ---------------------------------------------------------------------


def changes_from_diff(text: str, *, label: str = "pasted diff") -> ChangeSet:
    """Turn unified diff text (as `git diff` or a pull request's .diff prints it) into a ChangeSet."""
    if not text or not text.strip():
        raise SourceError("There is no diff to analyse. Paste the output of `git diff`.")
    if len(text.encode("utf-8", errors="ignore")) > MAX_DIFF_BYTES:
        raise SourceError(
            f"That diff is larger than {MAX_DIFF_BYTES // 1024} KB. Analyse a smaller change, "
            "or run ChangeRisk locally, which has no size limit.",
            413,
        )
    text = text.lstrip("﻿")
    if "diff --git " not in text:
        raise SourceError(
            "That does not look like a git diff. Paste the output of `git diff`, "
            "or the .diff of a pull request."
        )
    files = parse_diff(text)
    if not files:
        raise SourceError("No changed files were found in that diff.")
    truncated = False
    if len(files) > MAX_FILES:
        files, truncated = files[:MAX_FILES], True
    for fc in files:
        for hunk in fc.hunks:
            for line in hunk.lines:
                if len(line.text) > MAX_LINE_CHARS:
                    line.text = line.text[:MAX_LINE_CHARS]
    return ChangeSet(
        files=files, base="(pasted)", head="diff", mode="diff", repo_name=label, truncated=truncated
    )


# --- GitHub ---------------------------------------------------------------------

Transport = Callable[[str, Mapping[str, str]], tuple[int, Mapping[str, str], bytes]]


class _SameHostRedirects(urllib.request.HTTPRedirectHandler):
    """Follow redirects only to hosts we already trust, so a response cannot aim us elsewhere."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        if urlsplit(newurl).hostname not in ALLOWED_HOSTS:
            raise SourceError("GitHub redirected to an address this server will not follow.", 502)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def require_trusted(url: str) -> None:
    """Refuse anything but HTTPS to the two GitHub hosts."""
    if urlsplit(url).hostname not in ALLOWED_HOSTS or not url.startswith("https://"):
        raise SourceError("Refusing to contact that address.", 502)


def _urllib_transport(max_bytes: int) -> Transport:
    opener = urllib.request.build_opener(_SameHostRedirects)

    def fetch(url: str, headers: Mapping[str, str]) -> tuple[int, Mapping[str, str], bytes]:
        require_trusted(url)
        req = urllib.request.Request(url, headers=dict(headers))
        try:
            with opener.open(req, timeout=TIMEOUT) as resp:
                body = resp.read(max_bytes + 1)
                return resp.status, dict(resp.headers.items()), body
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers.items()) if exc.headers else {}, exc.read(65536)
        except (urllib.error.URLError, TimeoutError, OSError):
            raise SourceError("Could not reach GitHub. Try again in a moment.", 502) from None

    return fetch


class GitHub:
    def __init__(self, token: str | None = None, transport: Transport | None = None) -> None:
        self.token = token
        self._transport = transport or _urllib_transport(MAX_DIFF_BYTES)
        self.remaining: int | None = None  # from the last response's rate-limit header

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": "changerisk",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _get(self, path: str, accept: str = "application/vnd.github+json") -> bytes:
        status, headers, body = self._transport(f"https://{API_HOST}{path}", self._headers(accept))
        lower = {k.lower(): v for k, v in headers.items()}
        if "x-ratelimit-remaining" in lower:
            with contextlib.suppress(ValueError):
                self.remaining = int(lower["x-ratelimit-remaining"])
        if status == 200:
            if len(body) > MAX_DIFF_BYTES:
                raise SourceError(
                    "GitHub returned more than this server will analyse. Pick a smaller change.",
                    413,
                )
            return body
        raise _api_error(status, lower, body)

    def json(self, path: str) -> Any:
        body = self._get(path)  # may raise SourceError, which is itself a ValueError
        try:
            return json.loads(body)
        except ValueError:
            raise SourceError("GitHub sent a reply that could not be read.", 502) from None

    def diff(self, path: str) -> str:
        return self._get(path, "application/vnd.github.v3.diff").decode("utf-8", errors="replace")

    def raw(self, owner: str, repo: str, ref: str, path: str) -> str | None:
        """A file at a commit, from the raw host (which does not count against the API quota)."""
        url = f"https://{RAW_HOST}/{owner}/{repo}/{quote(ref, safe='')}/{quote(path)}"
        status, _, body = self._transport(url, {"User-Agent": "changerisk"})
        if status == 200 and len(body) <= MAX_CONFIG_BYTES:
            return body.decode("utf-8", errors="replace")
        return None


def _api_error(status: int, headers: Mapping[str, str], body: bytes) -> SourceError:
    text = body[:400].decode("utf-8", errors="replace").lower()
    if status == 404:
        return SourceError(
            "GitHub could not find that. Only public repositories can be analysed, "
            "and the pull request or branch has to exist.",
            404,
        )
    if status in (403, 429) and (
        "rate limit" in text or headers.get("x-ratelimit-remaining") == "0"
    ):
        wait = ""
        reset = headers.get("x-ratelimit-reset")
        if reset and reset.isdigit():
            minutes = round((int(reset) - time.time()) / 60)
            if minutes > 60:  # GitHub's window is an hour, so this clock is wrong; do not repeat it
                wait = " It resets within the hour."
            else:
                minutes = max(1, minutes)
                wait = f" It resets in about {minutes} minute{'s' if minutes != 1 else ''}."
        return SourceError(
            "GitHub's limit on anonymous requests has been reached." + wait + " "
            "You can paste the diff instead, which does not use GitHub.",
            429,
        )
    if status in (406, 422) and ("too_large" in text or "too large" in text or "exceeds" in text):
        return SourceError(
            "GitHub will not produce a diff for a change this large. Pick a smaller one, "
            "or run ChangeRisk locally.",
            413,
        )
    return SourceError(f"GitHub answered with status {status}.", 502)


def _config_from(gh: GitHub, owner: str, repo: str, ref: str) -> tuple[Config, str | None]:
    """The repository's own settings at `ref` (the base), or the defaults. Never raises."""
    from .rules.base import option_defaults

    for name in CONFIG_NAMES:
        text = gh.raw(owner, repo, ref, name)
        if text:
            try:
                import tomllib

                return parse_config(tomllib.loads(text), None, option_defaults()), name
            except (ConfigError, ValueError):
                return Config(), None  # a broken config should not stop an analysis
    return Config(), None


def changes_from_pull(gh: GitHub, ref: PullRef) -> tuple[ChangeSet, Config, list[str]]:
    base = f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}"
    pr = gh.json(base)
    diff = gh.diff(base)
    changes = changes_from_diff(diff, label=f"{ref.owner}/{ref.repo}")
    notes = [
        "Analysed from the pull request's diff on GitHub. History signals need a local clone "
        "and were skipped."
    ]

    commits: list[CommitInfo] = []
    try:
        for c in gh.json(f"{base}/commits?per_page=100"):
            info = c.get("commit", {})
            author = info.get("author") or {}
            commits.append(
                CommitInfo(
                    sha=str(c.get("sha", "")),
                    author=str(author.get("name", "")),
                    date=str(author.get("date", "")),
                    subject=str(info.get("message", "")).split("\n", 1)[0],
                )
            )
    except SourceError:
        notes.append("The commit list could not be loaded.")

    head_sha = pr["head"]["sha"]
    base_sha = pr["base"]["sha"]
    needs_tree = any(Classifier().is_manifest(f.path) for f in changes.files)
    if needs_tree:
        try:
            tree = gh.json(f"/repos/{ref.owner}/{ref.repo}/git/trees/{head_sha}?recursive=1")
            changes.repo_files = frozenset(
                t["path"] for t in tree.get("tree", []) if t.get("type") == "blob"
            )
            if tree.get("truncated"):
                notes.append(
                    "The repository is too large to list, so lockfile checks may be incomplete."
                )
        except SourceError:
            notes.append(
                "The repository's file list could not be loaded, so lockfile checks were skipped."
            )

    config, config_name = _config_from(gh, ref.owner, ref.repo, base_sha)
    if config_name:
        notes.append(f"Using {config_name} from the pull request's base commit.")

    changes.mode = "pr"
    changes.base = pr["base"]["ref"]
    changes.head = pr["head"].get("label") or pr["head"]["ref"]
    changes.base_sha, changes.head_sha, changes.merge_base = base_sha, head_sha, base_sha
    changes.commits = commits
    changes.source = {
        "type": "github",
        "url": pr.get("html_url", ""),
        "title": str(pr.get("title", ""))[:300],
        "number": ref.number,
        "author": (pr.get("user") or {}).get("login", ""),
        "state": "merged" if pr.get("merged_at") else pr.get("state", ""),
        "label": ref.label,
    }
    return changes, config, notes


def changes_from_compare(gh: GitHub, ref: CompareRef) -> tuple[ChangeSet, Config, list[str]]:
    path = f"/repos/{ref.owner}/{ref.repo}/compare/{quote(ref.base, safe='/')}...{quote(ref.head, safe='/:')}"
    diff = gh.diff(path)
    changes = changes_from_diff(diff, label=f"{ref.owner}/{ref.repo}")
    config, config_name = _config_from(gh, ref.owner, ref.repo, ref.base)
    notes = [
        "Analysed from a GitHub compare view. History signals and lockfile checks need a local "
        "clone and were skipped."
    ]
    if config_name:
        notes.append(f"Using {config_name} from {ref.base}.")
    changes.mode = "pr"
    changes.base, changes.head = ref.base, ref.head
    changes.source = {
        "type": "github",
        "url": f"https://github.com/{ref.owner}/{ref.repo}/compare/{ref.base}...{ref.head}",
        "title": "",
        "label": ref.label,
    }
    return changes, config, notes


MAX_LABEL_CHARS = 60


def _diff_label(label: object) -> str:
    """The name a diff is shown under. Optional, so a page can call a built-in example by its title."""
    if label is None:
        return "pasted diff"
    if not isinstance(label, str) or not label.strip() or not label.isprintable():
        raise SourceError("The diff's name has to be plain text.")
    if len(label) > MAX_LABEL_CHARS:
        raise SourceError(f"The diff's name has to be at most {MAX_LABEL_CHARS} characters.")
    return label.strip()


def load_source(gh: GitHub, source: dict[str, Any]) -> tuple[ChangeSet, Config, list[str]]:
    """Resolve a request's `source` object into a change, the config to use, and report notes."""
    kind = source.get("type")
    if kind == "diff":
        text = source.get("text")
        if not isinstance(text, str):
            raise SourceError("The diff has to be text.")
        label = _diff_label(source.get("label"))
        changes = changes_from_diff(text, label=label)
        changes.source = {"type": "diff", "label": label}
        return (
            changes,
            Config(),
            [
                "Analysed from a pasted diff. Lockfile and history checks need the repository "
                "and were skipped."
            ],
        )
    if kind == "github":
        url = source.get("url")
        if not isinstance(url, str):
            raise SourceError(_HINT)
        parsed = parse_source(url)
        if isinstance(parsed, PullRef):
            return changes_from_pull(gh, parsed)
        return changes_from_compare(gh, parsed)
    raise SourceError("The source has to be a pasted diff or a GitHub pull request.")
