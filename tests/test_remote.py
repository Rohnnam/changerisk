import json
import urllib.error
import urllib.request

import pytest

from changerisk import remote
from changerisk.remote import (
    CompareRef,
    GitHub,
    PullRef,
    SourceError,
    changes_from_diff,
    changes_from_pull,
    load_source,
    parse_source,
)

from .test_engine import risky_branch, seeded


@pytest.fixture
def diff_text(repo):
    seeded(repo)
    risky_branch(repo)
    return repo.git("diff", "main", "feature/speedup")


# --- parsing what the user typed ------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "https://github.com/acme/ledger/pull/42",
        "http://github.com/acme/ledger/pull/42/files",
        "github.com/acme/ledger/pull/42?diff=split#top",
        "https://www.github.com/acme/ledger/pull/42",
        "acme/ledger#42",
        "  acme/ledger#42  ",
    ],
)
def test_pull_request_forms(text):
    assert parse_source(text) == PullRef("acme", "ledger", 42)


def test_compare_url_with_slashes_in_branch_names():
    parsed = parse_source("https://github.com/acme/ledger/compare/main...feature/faster-checkout")
    assert parsed == CompareRef("acme", "ledger", "main", "feature/faster-checkout")
    assert parse_source("github.com/a/b/compare/v1.0...fork:topic") == CompareRef(
        "a", "b", "v1.0", "fork:topic"
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "not a url",
        "https://gitlab.com/acme/ledger/pull/42",
        "https://github.com.evil.example/acme/ledger/pull/42",
        "https://evil.example/github.com/acme/ledger/pull/42",
        "https://github.com/acme/ledger/issues/42",
        "https://github.com/acme/ledger/pull/abc",
        "https://github.com/acme/ledger/pull/12345678",
        "https://github.com/-bad/ledger/pull/1",
        "https://github.com/acme/ledger/compare/--upload-pack=x...main",
        "x" * 500,
    ],
)
def test_things_that_are_not_public_github_pull_requests(text):
    with pytest.raises(SourceError) as err:
        parse_source(text)
    assert err.value.status == 400
    assert "github" in str(err.value).lower() or "branch" in str(err.value).lower()


# --- diffs -----------------------------------------------------------------------


def test_a_real_git_diff_becomes_a_change_set(diff_text):
    cs = changes_from_diff(diff_text)
    assert cs.mode == "diff" and cs.base == "(pasted)"
    assert {f.path for f in cs.files} >= {"config/production.yml", "tests/test_refunds.py"}
    assert cs.additions > 0 and cs.deletions > 0


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ("", "no diff to analyse"),
        ("   \n", "no diff to analyse"),
        ("hello world", "does not look like a git diff"),
        ("--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b\n", "does not look like a git diff"),
        ("note: diff --git is how this starts\n", "No changed files"),
    ],
)
def test_bad_diffs_get_helpful_messages(text, fragment):
    with pytest.raises(SourceError, match=fragment):
        changes_from_diff(text)


def test_size_limit_and_line_truncation_and_file_cap(diff_text, monkeypatch):
    monkeypatch.setattr(remote, "MAX_DIFF_BYTES", 100)
    with pytest.raises(SourceError) as err:
        changes_from_diff(diff_text)
    assert err.value.status == 413 and "run ChangeRisk locally" in str(err.value)
    monkeypatch.undo()

    long_line = (
        "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+" + "x" * 50_000 + "\n"
    )
    (fc,) = changes_from_diff(long_line).files
    assert max(len(line.text) for line in fc.added_lines()) == remote.MAX_LINE_CHARS

    many = "".join(
        f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n@@ -0,0 +1 @@\n+x\n"
        for i in range(20)
    )
    monkeypatch.setattr(remote, "MAX_FILES", 5)
    cs = changes_from_diff(many)
    assert len(cs.files) == 5 and cs.truncated


def test_byte_order_mark_is_ignored(diff_text):
    assert changes_from_diff("﻿" + diff_text).files


# --- the GitHub client --------------------------------------------------------------


class FakeGitHub:
    """A transport that answers from a dict and records what was asked."""

    def __init__(self, routes, headers=None):
        self.routes = routes
        self.calls = []
        self.extra = headers or {}

    def __call__(self, url, headers):
        self.calls.append(url)
        for fragment, answer in self.routes.items():
            if fragment in url:
                status, body = answer
                body = body if isinstance(body, bytes) else json.dumps(body).encode()
                return status, dict(self.extra), body
        return 404, {}, b"{}"


def pull_routes(diff, **extra):
    routes = {
        "/pulls/7/commits": (
            200,
            [
                {
                    "sha": "c" * 40,
                    "commit": {
                        "author": {"name": "Ada", "date": "2026-01-01T00:00:00Z"},
                        "message": "Speed up\n\nbody",
                    },
                }
            ],
        ),
        "/pulls/7": (
            200,
            {
                "title": "Speed up checkout",
                "html_url": "https://github.com/acme/ledger/pull/7",
                "state": "open",
                "merged_at": None,
                "user": {"login": "ada"},
                "base": {"ref": "main", "sha": "a" * 40},
                "head": {"ref": "speedup", "label": "ada:speedup", "sha": "b" * 40},
            },
        ),
    }
    routes.update(extra)
    return routes


def test_pull_request_flow_uses_few_api_calls_and_only_trusted_hosts(diff_text):
    diff_answers = {}

    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if url.endswith("/pulls/7") and "v3.diff" in headers.get("Accept", ""):
                self.calls.append(url)
                return 200, {}, diff_text.encode()
            return super().__call__(url, headers)

    transport = Transport(pull_routes(diff_text))
    gh = GitHub(transport=transport)
    changes, config, notes = changes_from_pull(gh, PullRef("acme", "ledger", 7))

    assert changes.mode == "pr" and changes.base == "main" and changes.head == "ada:speedup"
    assert changes.source["label"] == "acme/ledger#7" and changes.source["author"] == "ada"
    assert changes.commits[0].subject == "Speed up" and changes.base_sha == "a" * 40
    assert config.fail_on is not None
    hosts = {u.split("/")[2] for u in transport.calls}
    assert hosts <= {"api.github.com", "raw.githubusercontent.com"}
    api_calls = [u for u in transport.calls if "api.github.com" in u]
    assert len(api_calls) == 4  # pull, diff, commits, tree (requirements.txt changed)
    assert any("History signals" in n for n in notes)
    assert diff_answers == {}


def test_tree_is_fetched_only_when_a_manifest_changed():
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n"

    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if url.endswith("/pulls/7") and "v3.diff" in headers.get("Accept", ""):
                self.calls.append(url)
                return 200, {}, diff.encode()
            return super().__call__(url, headers)

    transport = Transport(pull_routes(diff))
    changes_from_pull(GitHub(transport=transport), PullRef("acme", "ledger", 7))
    assert not any("/git/trees/" in u for u in transport.calls)


def test_repository_config_comes_from_the_base_commit():
    diff = "diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-a\n+b\n"

    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if url.endswith("/pulls/7") and "v3.diff" in headers.get("Accept", ""):
                return 200, {}, diff.encode()
            if "raw.githubusercontent.com" in url:
                self.calls.append(url)
                if url.endswith("/changerisk.toml"):
                    return 200, {}, b'[gate]\nfail_on = "never"\n'
                return 404, {}, b""
            return super().__call__(url, headers)

    transport = Transport(pull_routes(diff))
    _, config, notes = changes_from_pull(GitHub(transport=transport), PullRef("acme", "ledger", 7))
    assert config.fail_on is None
    assert any("changerisk.toml from the pull request's base commit" in n for n in notes)
    assert ("a" * 40) in " ".join(transport.calls)  # asked for the base sha, not the head


def test_a_broken_repository_config_does_not_stop_the_analysis():
    gh = GitHub(transport=FakeGitHub({"changerisk.toml": (200, b"[gat\nnope")}))
    config, name = remote._config_from(gh, "a", "b", "c" * 40)
    assert name is None and config.fail_on is not None


@pytest.mark.parametrize(
    ("status", "headers", "body", "expected_status", "fragment"),
    [
        (404, {}, b"{}", 404, "Only public repositories"),
        (
            403,
            {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "9999999999"},
            b"{}",
            429,
            "limit on anonymous requests",
        ),
        (429, {}, b'{"message":"API rate limit exceeded"}', 429, "paste the diff instead"),
        (406, {}, b'{"message":"diff exceeds the maximum number of lines"}', 413, "this large"),
        (500, {}, b"oops", 502, "status 500"),
    ],
)
def test_github_errors_become_plain_messages(status, headers, body, expected_status, fragment):
    def transport(url, hdrs):
        return status, headers, body

    with pytest.raises(SourceError) as err:
        GitHub(transport=transport).json("/repos/a/b/pulls/1")
    assert err.value.status == expected_status and fragment in str(err.value)


def test_the_rate_limit_message_gives_a_wait_only_when_it_can_be_believed(monkeypatch):
    monkeypatch.setattr(remote.time, "time", lambda: 1_000_000)

    def message(reset):
        headers = {"x-ratelimit-remaining": "0", "x-ratelimit-reset": str(reset)}
        with pytest.raises(SourceError) as err:
            GitHub(transport=lambda u, h: (403, headers, b"{}")).json("/repos/a/b/pulls/1")
        return str(err.value)

    assert "resets in about 5 minutes" in message(1_000_000 + 300)
    assert "resets in about 1 minute." in message(1_000_000 + 10)
    assert "resets in about 1 minute." in message(1_000_000 - 90)  # the clock ran ahead
    assert "resets within the hour" in message(1_000_000 + 6 * 3600)  # the clock is wrong
    assert "paste the diff instead" in message(1_000_000 + 300)


def test_a_diff_may_carry_a_short_plain_name():
    diff = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-x\n+y\n"
    gh = GitHub(transport=lambda u, h: (404, {}, b"{}"))
    changes, _, _ = remote.load_source(gh, {"type": "diff", "text": diff})
    assert changes.repo_name == "pasted diff" and changes.source["label"] == "pasted diff"
    named, _, _ = remote.load_source(
        gh, {"type": "diff", "text": diff, "label": "  Example: tidy  "}
    )
    assert named.repo_name == "Example: tidy" and named.source == {
        "type": "diff",
        "label": "Example: tidy",
    }
    for bad in ("", "   ", "x" * 61, "two\nlines", 7, ["a"]):
        with pytest.raises(SourceError, match="diff's name"):
            remote.load_source(gh, {"type": "diff", "text": diff, "label": bad})


def test_oversized_and_garbled_responses(monkeypatch):
    monkeypatch.setattr(remote, "MAX_DIFF_BYTES", 10)
    with pytest.raises(SourceError, match="more than this server will analyse"):
        GitHub(transport=lambda u, h: (200, {}, b"x" * 50)).diff("/x")
    monkeypatch.undo()
    with pytest.raises(SourceError, match="could not be read"):
        GitHub(transport=lambda u, h: (200, {}, b"<html>")).json("/x")


def test_rate_limit_header_is_tracked_and_token_is_sent():
    seen = {}

    def transport(url, headers):
        seen.update(headers)
        return 200, {"X-RateLimit-Remaining": "41"}, b"{}"

    gh = GitHub(token="tok", transport=transport)
    gh.json("/x")
    assert gh.remaining == 41 and seen["Authorization"] == "Bearer tok"
    anon = GitHub(transport=transport)
    anon.json("/x")
    assert "Authorization" not in seen or seen["Authorization"] == "Bearer tok"


def test_the_real_transport_refuses_untrusted_hosts_without_touching_the_network():
    fetch = remote._urllib_transport(1000)
    for url in (
        "https://evil.example/x",
        "http://api.github.com/x",
        "https://api.github.com.evil.example/x",
        "file:///etc/passwd",
    ):
        with pytest.raises(SourceError, match="Refusing"):
            fetch(url, {})


def test_redirects_off_the_trusted_hosts_are_refused():
    handler = remote._SameHostRedirects()
    req = urllib.request.Request("https://api.github.com/x")
    with pytest.raises(SourceError, match="redirected"):
        handler.redirect_request(req, None, 302, "Found", {}, "https://evil.example/steal")
    ok = handler.redirect_request(
        req, None, 301, "Moved", {}, "https://api.github.com/repositories/1/pulls/2"
    )
    assert ok is not None


# --- load_source ---------------------------------------------------------------------


def test_load_source_dispatch(diff_text):
    changes, config, notes = load_source(
        GitHub(transport=FakeGitHub({})), {"type": "diff", "text": diff_text}
    )
    assert changes.source == {"type": "diff", "label": "pasted diff"} and "pasted diff" in notes[0]
    for bad in ({}, {"type": "ftp"}, {"type": "diff", "text": 5}, {"type": "github", "url": 5}):
        with pytest.raises(SourceError):
            load_source(GitHub(transport=FakeGitHub({})), bad)
    with pytest.raises(SourceError, match="public GitHub pull request"):
        load_source(
            GitHub(transport=FakeGitHub({})), {"type": "github", "url": "https://example.com"}
        )


def test_compare_url_flow(diff_text):
    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if "/compare/main...topic" in url:
                self.calls.append(url)
                return 200, {}, diff_text.encode()
            return super().__call__(url, headers)

    changes, _, notes = load_source(
        GitHub(transport=Transport({})),
        {"type": "github", "url": "https://github.com/acme/ledger/compare/main...topic"},
    )
    assert (changes.mode, changes.base, changes.head) == ("pr", "main", "topic")
    assert changes.source["url"].endswith("/compare/main...topic") and "compare" in notes[0]
