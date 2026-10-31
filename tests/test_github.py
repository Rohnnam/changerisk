import json

import pytest

from changerisk import cli, github
from changerisk.reports import markdown

from .test_engine import risky_branch, seeded


def risky_branch_changes(repo):
    """The risky edits from the shared scenario, applied on the current branch."""
    from .test_engine import PROD_YML, STRIPE

    repo.write("config/production.yml", PROD_YML.replace("30", "300").replace("false", "true"))
    repo.write(
        "src/ledger/client.py",
        f'KEY = "{STRIPE}"\ndef charge(card, amount, currency):\n    return amount\n',
    )
    repo.commit("risky edits")


class FakeGitHub:
    """Stands in for api.github.com. Records calls and serves canned comment lists."""

    def __init__(self, comments=None, status=200):
        self.comments = comments or []
        self.status = status
        self.calls = []

    def __call__(self, method, url, headers, data):
        self.calls.append((method, url, json.loads(data) if data else None, dict(headers)))
        if self.status != 200 and method != "GET":
            return self.status, b"{}"
        if method == "GET":
            return 200, json.dumps(self.comments).encode()
        return (200 if method == "PATCH" else 201), b"{}"


def api(fake):
    return github.GitHubAPI("tok", "acme/ledgerline", "https://api.test", transport=fake)


def test_comment_is_created_when_none_exists():
    fake = FakeGitHub()
    assert github.upsert_comment(api(fake), 7, "body") == "comment created"
    method, url, payload, headers = fake.calls[-1]
    assert (method, url) == ("POST", "https://api.test/repos/acme/ledgerline/issues/7/comments")
    assert payload == {"body": "body"} and headers["Authorization"] == "Bearer tok"


def test_existing_comment_is_updated_in_place():
    fake = FakeGitHub(
        comments=[{"id": 1, "body": "hello"}, {"id": 42, "body": f"{markdown.MARKER}\nold"}]
    )
    assert github.upsert_comment(api(fake), 7, "new") == "comment updated"
    method, url, payload, _ = fake.calls[-1]
    assert (method, url) == ("PATCH", "https://api.test/repos/acme/ledgerline/issues/comments/42")
    assert payload == {"body": "new"}


@pytest.mark.parametrize("status", [401, 403, 404])
def test_read_only_tokens_degrade_quietly(status):
    result = github.upsert_comment(api(FakeGitHub(status=status)), 7, "x")
    assert result.startswith("comment skipped") and "forks" in result


def test_unexpected_status_is_reported():
    assert github.upsert_comment(api(FakeGitHub(status=500)), 7, "x") == "comment failed (HTTP 500)"


def test_listing_failure_does_not_raise():
    def broken(method, url, headers, data):
        return 500, b"oops"

    assert github.upsert_comment(api(broken), 7, "x").startswith("comment skipped")


def event_file(tmp_path, payload):
    p = tmp_path / "event.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return str(p)


def test_range_for_pull_request(repo, tmp_path):
    seeded(repo)
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": event_file(
            tmp_path, {"number": 12, "pull_request": {"base": {"sha": "abc123"}}}
        ),
        "GITHUB_SHA": "def456",
    }
    assert github.resolve_range(env, repo.root) == ("abc123", "def456", 12)


def test_range_for_push_and_first_push(repo, tmp_path):
    seeded(repo)
    env = {"GITHUB_EVENT_NAME": "push", "GITHUB_SHA": "after1",
           "GITHUB_EVENT_PATH": event_file(tmp_path, {"before": "bef0re", "after": "after1"})}  # fmt: skip
    assert github.resolve_range(env, repo.root) == ("bef0re", "after1", None)
    first = dict(
        env, GITHUB_EVENT_PATH=event_file(tmp_path, {"before": "0" * 40, "after": "after1"})
    )
    assert github.resolve_range(first, repo.root) == ("main", "after1", None)


def test_range_for_manual_runs_uses_default_branch(repo):
    seeded(repo)
    env = {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": "cafe"}
    assert github.resolve_range(env, repo.root) == ("main", "cafe", None)


def test_summary_and_outputs_files(tmp_path):
    summary, output = tmp_path / "summary.md", tmp_path / "output.txt"
    env = {"GITHUB_STEP_SUMMARY": str(summary), "GITHUB_OUTPUT": str(output)}
    assert github.write_summary(env, "# hi")
    assert summary.read_text(encoding="utf-8") == "# hi\n"
    assert not github.write_summary({}, "ignored")

    class R:
        score, failed_flag = 71, True
        gate_failed = True
        findings = [1, 2, 3]

        class level:
            label = "high"

    assert github.write_outputs(env, R())
    assert output.read_text(encoding="utf-8").splitlines() == [
        "score=71",
        "level=high",
        "failed=true",
        "findings=3",
    ]


def test_api_from_env_requires_token_and_repository():
    assert github.api_from_env({}) is None
    assert github.api_from_env({"GITHUB_TOKEN": "t"}) is None
    built = github.api_from_env({"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "a/b"})
    assert built.repository == "a/b" and built.api_url == "https://api.github.com"


def test_run_link():
    env = {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "a/b",
        "GITHUB_RUN_ID": "9",
    }
    assert github.run_link(env) == "https://github.com/a/b/actions/runs/9"
    assert github.run_link({}) is None


def test_ci_command_end_to_end(repo, tmp_path, monkeypatch, capsys):
    seeded(repo)
    risky_branch(repo)
    base_sha = repo.git("rev-parse", "main").strip()
    summary, output = tmp_path / "summary.md", tmp_path / "out.txt"
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": event_file(
            tmp_path, {"number": 5, "pull_request": {"base": {"sha": base_sha}}}
        ),
        "GITHUB_SHA": repo.git("rev-parse", "HEAD").strip(),
        "GITHUB_STEP_SUMMARY": str(summary),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_TOKEN": "tok",
        "GITHUB_REPOSITORY": "acme/ledgerline",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    fake = FakeGitHub()
    monkeypatch.setattr(
        github, "api_from_env",
        lambda e=None: github.GitHubAPI("tok", "acme/ledgerline", "https://api.test", transport=fake),
    )  # fmt: skip

    json_path = tmp_path / "report.json"
    code = cli.main(["ci", "--repo", str(repo.root), "--json", str(json_path), "--no-comment"])
    assert code == cli.EXIT_GATE
    out = capsys.readouterr()
    assert "::error " in out.out and "RISK  CRITICAL" in out.out
    assert "## ChangeRisk: Critical risk" in summary.read_text(encoding="utf-8")
    assert "failed=true" in output.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["level"] == "critical"
    assert fake.calls == []  # --no-comment

    cli.main(["ci", "--repo", str(repo.root), "--fail-on", "never"])
    assert any(call[0] == "POST" for call in fake.calls)


def pr_env(repo, tmp_path, monkeypatch):
    base_sha = repo.git("rev-parse", "main").strip()
    env = {
        "GITHUB_EVENT_NAME": "pull_request",
        "GITHUB_EVENT_PATH": event_file(
            tmp_path, {"number": 9, "pull_request": {"base": {"sha": base_sha}}}
        ),
        "GITHUB_SHA": repo.git("rev-parse", "HEAD").strip(),
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_a_pull_request_cannot_loosen_its_own_gate(repo, tmp_path, monkeypatch, capsys):
    seeded(repo)
    repo.write("changerisk.toml", '[gate]\nfail_on = "high"\n')
    repo.commit("gate on the base branch")
    repo.branch("sneaky")
    risky_branch_changes(repo)
    repo.write("changerisk.toml", '[gate]\nfail_on = "never"\n[paths]\nignore = ["**"]\n')
    repo.commit("risky change that also switches the gate off")
    pr_env(repo, tmp_path, monkeypatch)

    assert cli.main(["ci", "--repo", str(repo.root), "--no-comment"]) == cli.EXIT_GATE
    err = capsys.readouterr().err
    assert "configuration from the base branch" in err


def test_head_config_can_be_chosen_explicitly(repo, tmp_path, monkeypatch):
    seeded(repo)
    repo.write("changerisk.toml", '[gate]\nfail_on = "high"\n')
    repo.commit("gate on the base branch")
    repo.branch("trusted")
    risky_branch_changes(repo)
    repo.write("changerisk.toml", '[gate]\nfail_on = "never"\n')
    repo.commit("change that relaxes the gate on purpose")
    pr_env(repo, tmp_path, monkeypatch)

    assert (
        cli.main(["ci", "--repo", str(repo.root), "--no-comment", "--use-head-config"])
        == cli.EXIT_OK
    )


def test_pushes_use_the_checked_out_config(repo, tmp_path, monkeypatch):
    seeded(repo)
    repo.branch("feature")
    risky_branch_changes(repo)
    repo.write("changerisk.toml", '[gate]\nfail_on = "never"\n')
    repo.commit("risky, gate off")
    before = repo.git("rev-parse", "main").strip()
    after = repo.git("rev-parse", "HEAD").strip()
    monkeypatch.setenv("GITHUB_EVENT_NAME", "push")
    monkeypatch.setenv("GITHUB_SHA", after)
    monkeypatch.setenv(
        "GITHUB_EVENT_PATH", event_file(tmp_path, {"before": before, "after": after})
    )
    assert cli.main(["ci", "--repo", str(repo.root)]) == cli.EXIT_OK
