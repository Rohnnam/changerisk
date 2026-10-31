"""End to end: real repositories in, reports out."""

from changerisk import engine
from changerisk.config import Config, RuleSettings
from changerisk.models import Level

STRIPE = "sk_" + "live_" + "4eC39HqLyjWDarjtT1zdp7dc"

PROD_YML = "server:\n  request_timeout: 30\n  pool_size: 20\n  debug: false\n"
REFUND_TESTS = "".join(f"def test_case_{i}():\n    assert refund({i}) == {i}\n\n" for i in range(6))


def seeded(repo):
    repo.write("README.md", "# ledger\n")
    repo.write("config/production.yml", PROD_YML)
    repo.write("requirements.txt", "django==4.2.11\nrequests==2.31.0\n")
    repo.write("src/ledger/client.py", "def charge(card, amount):\n    return amount\n")
    repo.write("tests/test_refunds.py", REFUND_TESTS)
    repo.commit("initial")
    return repo


def risky_branch(repo):
    repo.branch("feature/speedup")
    repo.write("config/production.yml", PROD_YML.replace("30", "300").replace("false", "true"))
    repo.write("requirements.txt", "django==5.0.1\nrequests>=2.0\n")
    repo.write(
        "src/ledger/client.py",
        f'KEY = "{STRIPE}"\ndef charge(card, amount, currency):\n    return amount\n',
    )
    repo.remove("tests/test_refunds.py")
    repo.commit("Speed up checkout")


def test_risky_branch_gets_a_high_score_and_failing_gate(repo):
    seeded(repo)
    risky_branch(repo)

    report = engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)

    rules = {f.rule_id for f in report.findings}
    assert {"CFG001", "CFG002", "CFG003", "TST001", "SEC001", "DEP002", "DEP003", "API001"} <= rules
    assert report.level >= Level.HIGH
    assert report.gate_failed and report.fail_on == "high"
    assert report.score >= 75
    assert report.verdict.startswith(("This change needs", "Do not merge"))
    assert report.test_plan and report.test_plan[0].priority == 1
    assert [f.id for f in report.findings] == [f"f{i}" for i in range(1, len(report.findings) + 1)]
    assert STRIPE not in str(report.to_dict())


def test_findings_are_ranked_and_points_add_up(repo):
    seeded(repo)
    risky_branch(repo)
    report = engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)
    pts = [f.points for f in report.findings]
    assert pts == sorted(pts, reverse=True)
    assert abs(sum(pts) - report.points) < 1e-6


def test_file_report_attribution_and_flagged_diffs(repo):
    seeded(repo)
    risky_branch(repo)
    report = engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)
    files = {f.path: f for f in report.files}
    assert files["config/production.yml"].findings and files["config/production.yml"].hunks
    assert files["tests/test_refunds.py"].status == "deleted"
    assert report.files[0].points >= report.files[-1].points  # riskiest first
    unflagged = engine.analyze(
        repo.root, base="main", head="feature/speedup", use_history=False, include_diffs="none"
    )
    assert all(f.hunks is None for f in unflagged.files)


def test_docs_only_change_is_low_risk_and_passes(repo):
    seeded(repo)
    repo.branch("docs/typo")
    repo.write("README.md", "# ledger\n\nA typo fix.\n")
    repo.commit("Fix typo")
    report = engine.analyze(repo.root, base="main", head="docs/typo", use_history=False)
    assert report.findings == []
    assert (report.score, report.level, report.gate_failed) == (0, Level.LOW, False)
    assert report.verdict.startswith("No risky patterns found in 1 changed file.")


def test_no_changes(repo):
    seeded(repo)
    report = engine.analyze(repo.root, base="main", head="main", use_history=False)
    assert report.files == [] and report.verdict == "No changes to analyse."


def test_gate_can_be_overridden_and_turned_off(repo):
    seeded(repo)
    risky_branch(repo)
    off = engine.analyze(
        repo.root, base="main", head="feature/speedup", use_history=False, fail_on=None
    )
    assert off.gate_failed is False and off.fail_on == "never"
    crit = engine.analyze(
        repo.root, base="main", head="feature/speedup", use_history=False, fail_on="critical"
    )
    assert crit.fail_on == "critical"


def test_ignore_paths_and_disabled_rules(repo):
    seeded(repo)
    risky_branch(repo)
    cfg = Config(ignore=("config/**",), rules={"SEC001": RuleSettings(enabled=False)})
    report = engine.analyze(
        repo.root, base="main", head="feature/speedup", config=cfg, use_history=False
    )
    rules = {f.rule_id for f in report.findings}
    assert not any(r.startswith("CFG") for r in rules) and "SEC001" not in rules
    assert any("matched paths.ignore" in n for n in report.notes)


def test_a_crashing_rule_is_reported_not_fatal(repo, monkeypatch, capsys):
    seeded(repo)
    risky_branch(repo)
    from changerisk.rules.configuration import ConfigChanged

    def boom(self, ctx):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(ConfigChanged, "check", boom)
    report = engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)
    assert any("CFG001 failed" in n and "kaboom" in n for n in report.notes)
    assert "CFG001 failed" in capsys.readouterr().err
    assert report.findings  # the other rules still ran


def test_history_signals_flag_a_hotspot(repo):
    repo.write("src/pay.py", "v = 0\n")
    repo.commit("initial", author="Ada Lovelace")
    authors = ["Ada Lovelace", "Grace Hopper", "Linus Torvalds"]
    for i in range(1, 11):
        repo.write("src/pay.py", f"v = {i}\n")
        subject = f"Fix payment rounding bug {i}" if i % 2 else f"Tweak payment flow {i}"
        repo.commit(subject, author=authors[i % 3])
    repo.branch("topic")
    repo.write("src/pay.py", "v = 99\n")
    repo.commit("Another change")

    report = engine.analyze(repo.root, base="main", head="topic", use_history=True)
    hot = [f for f in report.findings if f.rule_id == "HIS001"]
    assert len(hot) == 1
    assert "changed 11 times" in hot[0].detail and "5 of them fixes" in hot[0].detail


def test_worktree_mode_sees_uncommitted_work(repo):
    seeded(repo)
    repo.write("config/production.yml", PROD_YML.replace("false", "true"))
    report = engine.analyze(repo.root, mode="worktree", use_history=False)
    assert report.mode == "worktree"
    assert any(f.rule_id == "CFG002" for f in report.findings)


def test_report_dict_shape(repo):
    seeded(repo)
    risky_branch(repo)
    d = engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False).to_dict()
    assert d["schema"] == "changerisk.report/1"
    assert set(d) >= {
        "range",
        "stats",
        "score",
        "level",
        "gate",
        "findings",
        "test_plan",
        "files",
        "categories",
        "notes",
    }
    assert d["range"]["base"] == "main" and d["stats"]["files"] == len(d["files"])
    first = d["findings"][0]
    assert set(first) >= {
        "id",
        "rule",
        "category",
        "title",
        "severity",
        "points",
        "detail",
        "paths",
        "evidence",
        "why",
        "test_focus",
    }


def test_whole_change_findings_do_not_flag_every_file(repo):
    seeded(repo)
    repo.branch("wide")
    for area in ("api", "web", "jobs", "reports", "infra"):
        repo.write(f"{area}/thing.py", "x = 1\n")
    repo.commit("touch many areas")
    report = engine.analyze(repo.root, base="main", head="wide", use_history=False)
    spread = [f for f in report.findings if f.rule_id == "SIZ002"]
    assert spread and spread[0].scope == "change"
    assert all(fr.points == 0 and not fr.findings for fr in report.files)
    assert report.to_dict()["findings"][0]["scope"] in ("change", "file")
