from changerisk.config import Config, RuleSettings
from changerisk.models import Severity
from changerisk.rules.dependencies import Dep, parse_dep

from .helpers import change, lines, run_rule

REQ_BEFORE = lines("django==4.2.11", "requests==2.31.0", "celery==5.3.6")


def test_parse_dep_requirements_variants():
    assert parse_dep("requirements.txt", "Django==4.2.11") == ("django", "==4.2.11")
    assert parse_dep("requirements.txt", "requests[security]>=2.0,<3") == ("requests", ">=2.0,<3")
    assert parse_dep("requirements.txt", "uvicorn") == ("uvicorn", "")
    assert parse_dep("requirements-dev.txt", "pytest ~= 8.0  # test runner") == ("pytest", "~=8.0")
    assert parse_dep("requirements.txt", "-r base.txt") is None
    assert parse_dep("requirements.txt", "# comment") is None


def test_parse_dep_other_manifests():
    assert parse_dep("pyproject.toml", '    "httpx>=0.27",') == ("httpx", ">=0.27")
    assert parse_dep("pyproject.toml", '    "git",') is None  # keyword, not a requirement
    assert parse_dep("pyproject.toml", 'version = "0.1.0"') is None
    assert parse_dep("pyproject.toml", 'django = "^4.2"') == ("django", "^4.2")
    assert parse_dep("package.json", '    "left-pad": "^1.3.0",') == ("left-pad", "^1.3.0")
    assert parse_dep("package.json", '  "version": "1.0.0",') is None
    assert parse_dep("go.mod", "\tgithub.com/gorilla/mux v1.8.0") == (
        "github.com/gorilla/mux",
        "v1.8.0",
    )
    assert parse_dep("Gemfile", "gem 'rails', '~> 7.0'") == ("rails", "~> 7.0")
    assert parse_dep("Cargo.toml", 'serde = { version = "1.0", features = ["derive"] }') == (
        "serde",
        "1.0",
    )
    assert parse_dep("build.gradle", "    implementation 'com.squareup.okhttp3:okhttp:4.12.0'") == (
        "com.squareup.okhttp3:okhttp", "4.12.0",
    )  # fmt: skip


def test_dep_pinned_and_version():
    assert Dep("a", "==1.2.3", 1, "").pinned
    assert Dep("a", "1.2.3", 1, "").pinned
    assert not Dep("a", "^1.2.3", 1, "").pinned
    assert not Dep("a", ">=1.2", 1, "").pinned
    assert not Dep("a", "", 1, "").pinned
    assert Dep("a", "==1.2", 1, "").version == (1, 2, 0)


def test_dep001_summarises_added_removed_changed():
    after = lines("django==4.2.12", "httpx==0.27.0", "celery==5.3.6")
    (f,) = run_rule("DEP001", change({"requirements.txt": (REQ_BEFORE, after)}))
    assert "added httpx ==0.27.0" in f.detail
    assert "removed requests" in f.detail
    assert "changed django ==4.2.11 to ==4.2.12" in f.detail
    assert f.severity == Severity.LOW


def test_dep001_many_changes_escalate_and_threshold_is_configurable():
    before = lines(*[f"p{i}==1.0" for i in range(6)])
    after = lines(*[f"p{i}==1.1" for i in range(6)])
    cs = change({"requirements.txt": (before, after)})
    assert run_rule("DEP001", cs)[0].severity == Severity.MEDIUM
    cfg = Config(rules={"DEP001": RuleSettings(options={"many": 20})})
    assert run_rule("DEP001", cs, cfg)[0].severity == Severity.LOW


def test_dep001_ignores_comment_only_and_non_manifest_changes():
    cs = change(
        {"requirements.txt": ("# a\ndjango==4\n", "# b\ndjango==4\n"), "src/x.py": ("a\n", "b\n")}
    )
    assert run_rule("DEP001", cs) == []


def test_dep002_major_bump_and_downgrade():
    after = lines("django==5.0.1", "requests==2.31.0", "celery==5.2.0")
    (f,) = run_rule("DEP002", change({"requirements.txt": (REQ_BEFORE, after)}))
    assert "django ==4.2.11 to ==5.0.1" in f.detail
    assert "celery ==5.3.6 to ==5.2.0 (downgrade)" in f.detail


def test_dep002_minor_bump_is_fine_but_zero_ver_minor_counts():
    minor = change({"requirements.txt": ("django==4.1.0\n", "django==4.2.0\n")})
    assert run_rule("DEP002", minor) == []
    zero = change({"requirements.txt": ("tool==0.3.0\n", "tool==0.4.0\n")})
    assert len(run_rule("DEP002", zero)) == 1


def test_dep003_pin_loosened():
    after = lines("django==4.2.11", "requests>=2.0", "celery")
    (f,) = run_rule("DEP003", change({"requirements.txt": (REQ_BEFORE, after)}))
    assert "requests ==2.31.0 to >=2.0" in f.detail
    assert "celery ==5.3.6 to (any version)" in f.detail


def test_dep003_tightening_is_fine():
    cs = change({"requirements.txt": ("requests>=2\n", "requests==2.31.0\n")})
    assert run_rule("DEP003", cs) == []


def test_dep004_lockfile_not_updated():
    before = lines('  "dependencies": {', '    "left-pad": "^1.2.0"', "  }")
    after = lines('  "dependencies": {', '    "left-pad": "^1.3.0"', "  }")
    cs = change({"web/package.json": (before, after)}, repo_files=["web/package-lock.json"])
    (f,) = run_rule("DEP004", cs)
    assert "web/package-lock.json was not updated" in f.detail
    assert "web/package-lock.json" in f.paths


def test_dep004_quiet_when_lockfile_moves_or_does_not_exist():
    before = lines('    "left-pad": "^1.2.0"')
    after = lines('    "left-pad": "^1.3.0"')
    both = change(
        {"package.json": (before, after), "package-lock.json": ("a\n", "b\n")},
        repo_files=["package-lock.json"],
    )
    assert run_rule("DEP004", both) == []
    no_lock = change({"package.json": (before, after)})
    assert run_rule("DEP004", no_lock) == []


def test_dep004_pyproject_with_uv_lock():
    before = lines("dependencies = [", '  "httpx>=0.26",', "]")
    after = lines("dependencies = [", '  "httpx>=0.27",', "]")
    cs = change({"pyproject.toml": (before, after)}, repo_files=["uv.lock"])
    assert len(run_rule("DEP004", cs)) == 1


def test_dep002_loosening_a_pin_is_not_called_a_downgrade():
    cs = change({"requirements.txt": ("requests==2.31.0\n", "requests>=2.0\n")})
    assert run_rule("DEP002", cs) == []
    caret = change({"package.json": ('    "left-pad": "^1.3.0"\n', '    "left-pad": "^0.9.0"\n')})
    assert "(downgrade)" in run_rule("DEP002", caret)[0].detail
