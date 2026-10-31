from changerisk.config import Config, RuleSettings
from changerisk.history import FileHistory, History
from changerisk.models import CommitInfo, Severity
from changerisk.rules.interfaces import public_symbols

from .helpers import change, lines, run_rule


def block(n: int, prefix: str = "x") -> str:
    return "".join(f"{prefix}{i} = {i}\n" for i in range(n))


# --- size -------------------------------------------------------------------


def test_siz001_thresholds():
    small = change({"src/a.py": ("", block(100))})
    assert run_rule("SIZ001", small) == []
    medium = change({"src/a.py": ("", block(250)), "src/b.py": ("", block(200))})
    (f,) = run_rule("SIZ001", medium)
    assert f.severity == Severity.MEDIUM and "450 lines changed across 2 files" in f.detail
    huge = change({"src/a.py": ("", block(1200))})
    assert run_rule("SIZ001", huge)[0].severity == Severity.HIGH


def test_siz001_does_not_count_docs_locks_or_generated():
    cs = change(
        {
            "README.md": ("", block(500)),
            "package-lock.json": ("", block(900)),
            "dist/x.js": ("", block(900)),
        }
    )
    assert run_rule("SIZ001", cs) == []


def test_siz001_thresholds_configurable():
    cs = change({"src/a.py": ("", block(100))})
    cfg = Config(rules={"SIZ001": RuleSettings(options={"medium_lines": 50})})
    assert len(run_rule("SIZ001", cs, cfg)) == 1


def test_siz002_spread():
    files = {f"{d}/f.py": ("", "x = 1\n") for d in ("api", "web", "jobs", "billing", "infra")}
    (f,) = run_rule("SIZ002", change(files))
    assert "5 areas" in f.detail
    assert run_rule("SIZ002", change(dict(list(files.items())[:4]))) == []


def test_siz003_big_file():
    cs = change({"src/a.py": ("", block(320)), "src/b.py": ("", block(10))})
    (f,) = run_rule("SIZ003", cs)
    assert f.paths == ["src/a.py"]


# --- history ----------------------------------------------------------------


def history(path, commits, fixes, authors=3):
    fh = FileHistory(commits=commits, fixes=fixes, authors={f"a{i}" for i in range(authors)})
    return History(days=90, window_start="2026-01-01", files={path: fh})


def test_his001_hotspot_with_fixes_escalates():
    cs = change({"src/payments/client.py": ("a\n", "b\n")})
    hot = history("src/payments/client.py", commits=12, fixes=6)
    (f,) = run_rule("HIS001", cs, history=hot)
    assert f.severity == Severity.HIGH
    assert "12 times in the 90 days" in f.detail and "6 of them fixes" in f.detail


def test_his001_busy_but_clean_file_is_medium_and_quiet_file_is_ignored():
    cs = change({"src/a.py": ("a\n", "b\n")})
    busy = history("src/a.py", commits=10, fixes=1)
    assert run_rule("HIS001", cs, history=busy)[0].severity == Severity.MEDIUM
    quiet = history("src/a.py", commits=3, fixes=3)
    assert run_rule("HIS001", cs, history=quiet) == []


def test_his001_without_history_is_silent():
    assert run_rule("HIS001", change({"src/a.py": ("a\n", "b\n")})) == []


def test_his002_reverts():
    commits = [
        CommitInfo("a" * 40, "x", "2026-01-01", 'Revert "Add retry loop"'),
        CommitInfo("b" * 40, "x", "2026-01-02", "Add retry loop"),
    ]
    (f,) = run_rule("HIS002", change({"src/a.py": ("a\n", "b\n")}, commits=commits))
    assert f.severity == Severity.LOW and "Add retry loop" in f.detail
    again = [CommitInfo("c" * 40, "x", "2026-01-03", 'Revert "Revert "Add retry loop""')]
    assert (
        run_rule("HIS002", change({"src/a.py": ("a\n", "b\n")}, commits=again))[0].severity
        == Severity.MEDIUM
    )


# --- interfaces -------------------------------------------------------------

API_BEFORE = lines(
    "import os",
    "",
    "def charge(card, amount):",
    "    return 1",
    "",
    "def refund(charge_id):",
    "    return 2",
    "",
    "def _private():",
    "    return 3",
    "",
    "class Ledger:",
    "    pass",
)


def test_api001_removed_and_changed_signatures():
    after = API_BEFORE.replace(
        "def charge(card, amount):", "def charge(card, amount, currency):"
    ).replace("def refund(charge_id):\n    return 2\n", "")
    (f,) = run_rule("API001", change({"src/ledgerline/api.py": (API_BEFORE, after)}))
    assert "removed refund()" in f.detail
    assert "changed the signature of charge" in f.detail


def test_api001_private_names_additions_and_body_edits_are_fine():
    after = API_BEFORE.replace("def _private():", "def _renamed_private():").replace(
        "return 1", "return 10"
    )
    assert run_rule("API001", change({"src/api.py": (API_BEFORE, after)})) == []
    added = API_BEFORE + "\ndef brand_new():\n    pass\n"
    assert run_rule("API001", change({"src/api.py": (API_BEFORE, added)})) == []


def test_api001_moved_symbol_is_not_a_removal():
    after = API_BEFORE.replace("def refund(charge_id):\n    return 2\n", "")
    moved = lines("def refund(charge_id):", "    return 2")
    cs = change({"src/api.py": (API_BEFORE, after), "src/refunds.py": (None, moved)})
    assert run_rule("API001", cs) == []


def test_api001_typescript_exports():
    before = lines("export function add(a: number, b: number) {", "}", "export const PI = 3")
    after = lines("export const PI = 3")
    (f,) = run_rule("API001", change({"web/math.ts": (before, after)}))
    assert "removed add" in f.detail


def test_api001_skips_tests():
    cs = change({"tests/helpers.py": ("def helper():\n    pass\n", "")})
    assert run_rule("API001", cs) == []


def test_public_symbols_go():
    syms = public_symbols(
        [
            (1, "func Run(ctx context.Context) error {"),
            (5, "func helper() {"),
            (9, "func (s *Server) Start() {"),
        ],
        "go",
    )
    assert set(syms) == {"Run", "Start"}


def test_api002_contract_files():
    before = lines("message Charge {", "  int64 amount = 1;", "  string currency = 2;", "}")
    after = lines("message Charge {", "  int64 amount = 1;", "}")
    (f,) = run_rule("API002", change({"api/charge.proto": (before, after)}))
    assert f.severity == Severity.HIGH and "1 of its lines were removed" in f.detail
    additive = change({"api/charge.proto": (before, before.replace("}", "  string note = 3;\n}"))})
    assert run_rule("API002", additive)[0].severity == Severity.MEDIUM


# --- code patterns ----------------------------------------------------------


def test_cod001_risky_calls_in_python():
    src = lines(
        "import subprocess",
        "subprocess.run(cmd, shell=True)",
        "data = pickle.loads(blob)",
        "x = eval(user)",
    )
    (f,) = run_rule("COD001", change({"src/run.py": ("", src)}))
    assert "shell=True" in f.detail and "pickle" in f.detail
    assert f.severity == Severity.HIGH


def test_cod001_sql_built_with_fstring_and_js_innerhtml():
    sql = change({"src/db.py": ("", 'cur.execute(f"SELECT * FROM t WHERE id = {user_id}")\n')})
    assert "f-string" in run_rule("COD001", sql)[0].detail
    js = change({"web/app.js": ("", "el.innerHTML = html;\n")})
    assert run_rule("COD001", js)[0].severity == Severity.MEDIUM


def test_cod001_ignores_comments_tests_and_safe_variants():
    assert run_rule("COD001", change({"src/a.py": ("", "# eval(x)\n")})) == []
    assert run_rule("COD001", change({"tests/test_a.py": ("", "eval(x)\n")})) == []
    assert (
        run_rule("COD001", change({"src/a.py": ("", "yaml.load(f, Loader=yaml.SafeLoader)\n")}))
        == []
    )
    assert run_rule("COD001", change({"src/a.py": ("", "literal_eval(x)\n")})) == []


def test_cod002_swallowed_exception_python_and_js():
    py = lines("try:", "    risky()", "except Exception:", "    pass")
    (f,) = run_rule("COD002", change({"src/a.py": ("", py)}))
    assert "ignore the error" in f.detail
    js = change({"web/a.js": ("", "try { go(); } catch (e) {}\n")})
    assert len(run_rule("COD002", js)) == 1
    ok = lines("try:", "    risky()", "except ValueError:", "    log.warning('x')")
    assert run_rule("COD002", change({"src/a.py": ("", ok)})) == []


def test_cod002_removed_handlers():
    before = lines(
        "try:",
        "    a()",
        "except KeyError:",
        "    b()",
        "try:",
        "    c()",
        "except OSError:",
        "    d()",
    )
    after = lines("a()", "c()")
    (f,) = run_rule("COD002", change({"src/a.py": (before, after)}))
    assert "2 error handlers removed" in f.detail


def test_cod003_suppressions():
    src = lines("import x  # noqa", "y = f()  # type: ignore")
    (f,) = run_rule("COD003", change({"src/a.py": ("", src)}))
    assert f.severity == Severity.LOW and "2 lint or type checks" in f.detail
    nosec = change({"src/a.py": ("", "h = md5(x)  # nosec\n")})
    assert run_rule("COD003", nosec)[0].severity == Severity.MEDIUM


def test_whole_change_findings_are_scoped_to_the_change():
    files = {f"{d}/f.py": ("", "x = 1\n") for d in ("api", "web", "jobs", "billing", "infra")}
    assert run_rule("SIZ002", change(files))[0].scope == "change"
    assert run_rule("SIZ001", change({"src/a.py": ("", block(500))}))[0].scope == "change"
    assert run_rule("TST005", change({"src/a.py": ("", block(40))}))[0].scope == "change"
    assert run_rule("SIZ003", change({"src/a.py": ("", block(500))}))[0].scope == "file"
