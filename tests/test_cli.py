import json

import pytest

from changerisk import cli

from .test_engine import risky_branch, seeded


@pytest.fixture
def risky(repo):
    seeded(repo)
    risky_branch(repo)
    return repo


@pytest.fixture
def calm(repo):
    seeded(repo)
    repo.branch("docs/typo")
    repo.write("README.md", "# ledger\n\nfixed\n")
    repo.commit("typo")
    return repo


def run(*args):
    return cli.main(list(args))


def test_exit_one_when_the_gate_trips(risky, capsys):
    code = run(
        "analyze",
        "--repo",
        str(risky.root),
        "--base",
        "main",
        "--head",
        "feature/speedup",
        "--no-history",
    )
    out = capsys.readouterr().out
    assert code == cli.EXIT_GATE
    assert "RISK  CRITICAL" in out


def test_exit_zero_on_a_calm_change(calm, capsys):
    code = run("analyze", "--repo", str(calm.root), "--base", "main", "--head", "docs/typo")
    assert code == cli.EXIT_OK
    assert "RISK  LOW" in capsys.readouterr().out


def test_fail_on_never_and_quiet(risky, capsys):
    args = [
        "analyze",
        "--repo",
        str(risky.root),
        "--base",
        "main",
        "--head",
        "feature/speedup",
        "--no-history",
    ]
    assert run(*args, "--fail-on", "never", "--quiet") == cli.EXIT_OK
    assert capsys.readouterr().out == ""


def test_fail_on_critical_still_trips_here(risky):
    args = [
        "analyze",
        "--repo",
        str(risky.root),
        "--base",
        "main",
        "--head",
        "feature/speedup",
        "--no-history",
    ]
    assert run(*args, "--fail-on", "critical", "-q") == cli.EXIT_GATE


def test_json_to_stdout_and_to_file(risky, capsys, tmp_path):
    args = [
        "analyze",
        "--repo",
        str(risky.root),
        "--base",
        "main",
        "--head",
        "feature/speedup",
        "--no-history",
    ]
    run(*args, "-f", "json", "--fail-on", "never")
    data = json.loads(capsys.readouterr().out)
    assert data["level"] == "critical"
    target = tmp_path / "r.json"
    run(*args, "-f", "markdown", "-o", str(target), "--fail-on", "never")
    assert target.read_text(encoding="utf-8").startswith("<!-- changerisk-report -->")


def test_staged_mode(repo, capsys):
    seeded(repo)
    repo.write("config/production.yml", "server:\n  debug: true\n")
    repo.git("add", "config/production.yml")
    assert (
        run("analyze", "--repo", str(repo.root), "--staged", "--no-history", "-f", "json")
        == cli.EXIT_GATE
    )
    assert json.loads(capsys.readouterr().out)["range"]["mode"] == "staged"


def test_staged_cannot_be_mixed_with_base(repo, capsys):
    seeded(repo)
    assert run("analyze", "--repo", str(repo.root), "--staged", "--base", "main") == cli.EXIT_USAGE
    assert "cannot be combined" in capsys.readouterr().err


def test_bad_config_is_a_usage_error(repo, capsys):
    seeded(repo)
    (repo.root / "changerisk.toml").write_text('[gat]\nfail_on = "high"\n', encoding="utf-8")
    assert (
        run("analyze", "--repo", str(repo.root), "--base", "main", "--head", "main")
        == cli.EXIT_USAGE
    )
    assert "unknown section [gat]" in capsys.readouterr().err


def test_unknown_revision_is_a_failure_with_a_message(repo, capsys):
    seeded(repo)
    assert run("analyze", "--repo", str(repo.root), "--base", "nope") == cli.EXIT_FAILURE
    assert "unknown revision 'nope'" in capsys.readouterr().err


def test_not_a_repo(tmp_path, capsys):
    assert run("analyze", "--repo", str(tmp_path)) == cli.EXIT_FAILURE
    assert "not inside a git repository" in capsys.readouterr().err


def test_rules_listing_and_detail(capsys):
    assert run("rules") == cli.EXIT_OK
    listing = capsys.readouterr().out
    assert listing.count("\n") == 33 and "TST001" in listing
    assert run("rules", "tst001") == cli.EXIT_OK
    detail = capsys.readouterr().out
    assert "Test file deleted" in detail and "why:" in detail and "test:" in detail
    assert run("rules", "SIZ001") == cli.EXIT_OK
    assert "medium_lines = 400" in capsys.readouterr().out


def test_rules_json_and_unknown(capsys):
    assert run("rules", "--json") == cli.EXIT_OK
    assert len(json.loads(capsys.readouterr().out)) == 33
    assert run("rules", "ZZZ999") == cli.EXIT_USAGE
    assert "Known rules" in capsys.readouterr().err


def test_init_writes_a_valid_config_once(repo, capsys):
    seeded(repo)
    assert run("init", "--repo", str(repo.root)) == cli.EXIT_OK
    assert (repo.root / "changerisk.toml").exists()
    assert run("init", "--repo", str(repo.root)) == cli.EXIT_USAGE
    assert "already exists" in capsys.readouterr().err
    assert run("init", "--repo", str(repo.root), "--force") == cli.EXIT_OK


def test_no_command_prints_help(capsys):
    assert run() == cli.EXIT_USAGE
    assert "usage: changerisk" in capsys.readouterr().out


def test_version(capsys):
    with pytest.raises(SystemExit) as stop:
        run("--version")
    assert stop.value.code == 0
    assert capsys.readouterr().out.startswith("changerisk 0.1.0")


@pytest.mark.parametrize(
    ("env", "tty", "expected"),
    [({}, False, False), ({"NO_COLOR": "1"}, True, False), ({"FORCE_COLOR": "1"}, False, True)],
)
def test_colour_decision(monkeypatch, env, tty, expected):
    for var in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(var, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    class Stream:
        def isatty(self):
            return tty

    assert cli.use_color(Stream()) is expected


def test_python_dash_m_entry_point():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-m", "changerisk", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0 and out.stdout.startswith("changerisk ")
