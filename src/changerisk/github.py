"""GitHub Actions glue: work out the range from the event, post the comment, write the summary."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from pathlib import Path

from . import gitops
from .models import RiskReport
from .reports import markdown

ZERO_SHA = "0" * 40
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


def _event(env: Mapping[str, str]) -> dict:
    path = env.get("GITHUB_EVENT_PATH")
    if not path or not Path(path).is_file():
        return {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_range(env: Mapping[str, str], repo: Path) -> tuple[str | None, str, int | None]:
    """Pick (base, head, pull request number) for the event this workflow run was started by."""
    name = env.get("GITHUB_EVENT_NAME", "")
    payload = _event(env)
    sha = env.get("GITHUB_SHA") or "HEAD"

    if name in ("pull_request", "pull_request_target") and "pull_request" in payload:
        pr = payload["pull_request"]
        return pr["base"]["sha"], sha, int(payload.get("number") or pr.get("number"))

    if name == "push":
        before = payload.get("before") or ""
        if before and before != ZERO_SHA:
            return before, payload.get("after") or sha, None
        # first push of a branch: compare against the default branch, or the previous commit
        return gitops.default_base(repo) or "HEAD~1", sha, None

    return gitops.default_base(repo), sha, None


class GitHubAPI:
    def __init__(
        self,
        token: str,
        repository: str,
        api_url: str = "https://api.github.com",
        transport: Transport | None = None,
    ) -> None:
        self.token = token
        self.repository = repository
        self.api_url = api_url.rstrip("/")
        self._transport = transport or self._urllib

    @staticmethod
    def _urllib(
        method: str, url: str, headers: Mapping[str, str], data: bytes | None
    ) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=data, method=method, headers=dict(headers))
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 (https only, fixed host)
                return resp.status, resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "changerisk",
        }
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        status, raw = self._transport(method, f"{self.api_url}{path}", headers, data)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, None

    def find_comment(self, pr_number: int) -> int | None:
        for page in range(1, 11):
            status, items = self.call(
                "GET",
                f"/repos/{self.repository}/issues/{pr_number}/comments?per_page=100&page={page}",
            )
            if status != 200 or not isinstance(items, list):
                raise RuntimeError(f"could not list comments (HTTP {status})")
            for item in items:
                if markdown.MARKER in (item.get("body") or ""):
                    return int(item["id"])
            if len(items) < 100:
                break
        return None


def upsert_comment(api: GitHubAPI, pr_number: int, body: str) -> str:
    """Create the report comment, or update the one a previous run left. Returns a status line."""
    try:
        existing = api.find_comment(pr_number)
        if existing is not None:
            status, _ = api.call(
                "PATCH", f"/repos/{api.repository}/issues/comments/{existing}", {"body": body}
            )
            verb = "updated"
        else:
            status, _ = api.call(
                "POST", f"/repos/{api.repository}/issues/{pr_number}/comments", {"body": body}
            )
            verb = "created"
    except (RuntimeError, OSError) as exc:
        return f"comment skipped: {exc}"
    if status in (200, 201):
        return f"comment {verb}"
    if status in (401, 403, 404):
        return (
            f"comment skipped (HTTP {status}): the token cannot write to this pull request, "
            "which is normal for pull requests from forks"
        )
    return f"comment failed (HTTP {status})"


def write_summary(env: Mapping[str, str], text: str) -> bool:
    target = env.get("GITHUB_STEP_SUMMARY")
    if not target:
        return False
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")
    return True


def write_outputs(env: Mapping[str, str], report: RiskReport) -> bool:
    target = env.get("GITHUB_OUTPUT")
    if not target:
        return False
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(f"score={report.score}\n")
        fh.write(f"level={report.level.label}\n")
        fh.write(f"failed={'true' if report.gate_failed else 'false'}\n")
        fh.write(f"findings={len(report.findings)}\n")
    return True


def api_from_env(env: Mapping[str, str] = os.environ) -> GitHubAPI | None:
    token = env.get("GITHUB_TOKEN") or env.get("INPUT_GITHUB_TOKEN")
    repository = env.get("GITHUB_REPOSITORY")
    if not token or not repository:
        return None
    return GitHubAPI(token, repository, env.get("GITHUB_API_URL", "https://api.github.com"))


def run_link(env: Mapping[str, str]) -> str | None:
    server, repo, run = (
        env.get("GITHUB_SERVER_URL"),
        env.get("GITHUB_REPOSITORY"),
        env.get("GITHUB_RUN_ID"),
    )
    if server and repo and run:
        return f"{server}/{repo}/actions/runs/{run}"
    return None
