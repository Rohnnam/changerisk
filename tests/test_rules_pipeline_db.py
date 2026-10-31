from changerisk.models import Severity

from .helpers import change, lines, run_rule

CI = lines(
    "name: ci",
    "on: [push]",
    "jobs:",
    "  test:",
    "    runs-on: ubuntu-latest",
    "    steps:",
    "      - uses: actions/checkout@v4",
    "      - run: pytest",
)
WF = ".github/workflows/ci.yml"


# --- CI ---------------------------------------------------------------------


def test_ci001_any_workflow_edit_is_reported_deploy_ones_higher():
    cs = change({WF: (CI, CI.replace("ubuntu-latest", "ubuntu-22.04"))})
    (f,) = run_rule("CI001", cs)
    assert f.severity == Severity.MEDIUM
    deploy = change({".github/workflows/deploy.yml": (CI, CI + "      - run: echo hi\n")})
    assert run_rule("CI001", deploy)[0].severity == Severity.HIGH


def test_ci001_ignores_other_files():
    assert run_rule("CI001", change({"src/a.py": ("a\n", "b\n")})) == []


def test_ci002_continue_on_error_and_or_true():
    after = CI.replace("- run: pytest", "- run: pytest || true\n        continue-on-error: true")
    (f,) = run_rule("CI002", change({WF: (CI, after)}))
    assert "continue-on-error" in f.detail
    assert "|| true" in f.detail
    assert f.severity == Severity.HIGH


def test_ci002_removed_test_step():
    after = CI.replace("      - run: pytest\n", "")
    (f,) = run_rule("CI002", change({WF: (CI, after)}))
    assert "1 test or lint command removed" in f.detail
    assert f.evidence[0].side == "old"


def test_ci002_replacing_a_command_is_not_removal():
    after = CI.replace("pytest", "pytest -x")
    assert run_rule("CI002", change({WF: (CI, after)})) == []


def test_ci003_permissions_and_unpinned_actions():
    after = CI.replace("on: [push]", "on: [push]\npermissions: write-all").replace(
        "actions/checkout@v4", "someorg/action@main"
    )
    (f,) = run_rule("CI003", change({WF: (CI, after)}))
    assert "write-all" in f.detail and "moving branch" in f.detail
    assert f.severity == Severity.HIGH


def test_ci003_pull_request_target_checking_out_pr_code_is_critical():
    after = CI.replace("on: [push]", "on: [pull_request_target]").replace(
        "- uses: actions/checkout@v4",
        "- uses: actions/checkout@v4\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}",
    )
    (f,) = run_rule("CI003", change({WF: (CI, after)}))
    assert f.severity == Severity.CRITICAL
    assert "checks out the pull request" in f.detail


def test_ci003_only_github_workflows():
    cs = change({".gitlab-ci.yml": ("a\n", "permissions: write-all\n")})
    assert run_rule("CI003", cs) == []


# --- DB ---------------------------------------------------------------------

MIG = "db/migrations/0005_drop_legacy.sql"


def test_db001_new_migration_lists_its_statements():
    cs = change(
        {
            MIG: (
                None,
                "-- cleanup\nALTER TABLE ledger ADD COLUMN note text;\nCREATE INDEX idx ON ledger (note);\n",
            )
        }
    )
    (f,) = run_rule("DB001", cs)
    assert f.severity == Severity.MEDIUM
    assert len(f.evidence) == 2


def test_db001_ignores_edits_and_non_migrations():
    assert run_rule("DB001", change({MIG: ("a\n", "b\n")})) == []
    assert run_rule("DB001", change({"src/a.sql": (None, "select 1;\n")})) == []


def test_db002_drop_and_truncate():
    cs = change({MIG: (None, "DROP TABLE legacy_ledger;\nTRUNCATE audit_log;\n")})
    (f,) = run_rule("DB002", cs)
    assert "drops a table" in f.detail and "truncates" in f.detail
    assert f.severity == Severity.HIGH


def test_db002_drop_database_is_critical():
    cs = change({MIG: (None, "DROP SCHEMA reporting CASCADE;\n")})
    assert run_rule("DB002", cs)[0].severity == Severity.CRITICAL


def test_db002_rename_and_not_null_are_medium():
    cs = change({MIG: (None, "ALTER TABLE t RENAME COLUMN a TO b;\n")})
    assert run_rule("DB002", cs)[0].severity == Severity.MEDIUM
    nn = change({MIG: (None, "ALTER TABLE t ADD COLUMN c int NOT NULL;\n")})
    assert "NOT NULL" in run_rule("DB002", nn)[0].detail
    ok = change({MIG: (None, "ALTER TABLE t ADD COLUMN c int NOT NULL DEFAULT 0;\n")})
    assert run_rule("DB002", ok) == []


def test_db002_delete_without_where_but_not_with_where():
    assert len(run_rule("DB002", change({MIG: (None, "DELETE FROM sessions;\n")}))) == 1
    assert run_rule("DB002", change({MIG: (None, "DELETE FROM sessions WHERE expired;\n")})) == []


def test_db002_python_migrations_and_comments():
    py = change(
        {"app/migrations/0002_x.py": (None, "def upgrade():\n    op.drop_column('t', 'c')\n")}
    )
    assert len(run_rule("DB002", py)) == 1
    commented = change({MIG: (None, "-- DROP TABLE old;\n")})
    assert run_rule("DB002", commented) == []


def test_db003_editing_an_existing_migration():
    cs = change(
        {
            "db/migrations/0003_add.sql": (
                "CREATE TABLE a (id int);\n",
                "CREATE TABLE a (id bigint);\n",
            )
        }
    )
    (f,) = run_rule("DB003", cs)
    assert f.severity == Severity.HIGH
    assert "edited" in f.detail
    gone = change({"db/migrations/0003_add.sql": ("CREATE TABLE a (id int);\n", None)})
    assert "deleted" in run_rule("DB003", gone)[0].detail


def test_db003_new_migrations_and_snapshots_are_fine():
    assert run_rule("DB003", change({MIG: (None, "select 1;\n")})) == []
    assert run_rule("DB003", change({"db/schema.rb": ("a\n", "b\n")})) == []
