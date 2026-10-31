from changerisk.config import Config, RuleSettings
from changerisk.models import Severity
from changerisk.rules.testing import find_cases

from .helpers import change, lines, run_rule

REFUNDS = lines(
    "import pytest",
    "",
    "def test_full_refund():",
    "    assert refund(10) == 10",
    "",
    "def test_partial_refund():",
    "    assert refund(5) == 5",
    "",
    "async def test_refund_after_chargeback():",
    "    assert await refund(1) == 0",
)


# --- TST001 -----------------------------------------------------------------


def test_tst001_deleted_test_file_counts_lost_cases():
    cs = change({"tests/test_refunds.py": (REFUNDS, None)})
    (f,) = run_rule("TST001", cs)
    assert f.severity == Severity.HIGH
    assert "removing 3 test cases" in f.detail
    assert {e.text for e in f.evidence} == {
        "test_full_refund", "test_partial_refund", "test_refund_after_chargeback",
    }  # fmt: skip
    assert all(e.side == "old" for e in f.evidence)


def test_tst001_moved_tests_are_not_a_loss():
    cs = change({
        "tests/test_refunds.py": (REFUNDS, None),
        "tests/payments/test_refunds.py": (None, REFUNDS),
    })  # fmt: skip
    assert run_rule("TST001", cs) == []


def test_tst001_ignores_non_test_deletions():
    assert run_rule("TST001", change({"src/old.py": ("x = 1\n", None)})) == []


def test_tst001_deleted_conftest_without_cases_still_reports():
    cs = change({"tests/conftest.py": ("import pytest\n\n@pytest.fixture\ndef db(): ...\n", None)})
    (f,) = run_rule("TST001", cs)
    assert "was deleted" in f.detail


# --- TST002 -----------------------------------------------------------------


def test_tst002_removed_cases_in_surviving_file():
    after = REFUNDS.replace("def test_partial_refund():\n    assert refund(5) == 5\n", "")
    (f,) = run_rule("TST002", change({"tests/test_refunds.py": (REFUNDS, after)}))
    assert "lost 1 test case: test_partial_refund" in f.detail
    assert f.severity == Severity.MEDIUM
    assert f.evidence[0].line == 6


def test_tst002_three_or_more_is_high():
    after = lines("import pytest")
    (f,) = run_rule("TST002", change({"tests/test_refunds.py": (REFUNDS, after)}))
    assert f.severity == Severity.HIGH


def test_tst002_renamed_test_is_not_a_removal():
    after = REFUNDS.replace("test_full_refund", "test_refunds_the_full_amount")
    assert run_rule("TST002", change({"tests/test_refunds.py": (REFUNDS, after)})) == []


def test_tst002_javascript_and_go_and_annotation_styles():
    js_before = lines(
        "describe('x', () => {",
        "  it('adds', () => {",
        "  });",
        '  test("subtracts", () => {',
        "  });",
        "});",
    )
    js_after = lines("describe('x', () => {", "  it('adds', () => {", "  });", "});")
    (f,) = run_rule("TST002", change({"web/math.test.ts": (js_before, js_after)}))
    assert "subtracts" in f.detail

    go_before = lines("func TestA(t *testing.T) {", "}", "func TestB(t *testing.T) {", "}")
    go_after = lines("func TestA(t *testing.T) {", "}")
    (g,) = run_rule("TST002", change({"pkg/a_test.go": (go_before, go_after)}))
    assert "TestB" in g.detail

    java_before = lines(
        "class FooTest {",
        "  @Test",
        "  public void adds() {}",
        "  @Test",
        "  public void subtracts() {}",
        "}",
    )
    java_after = lines("class FooTest {", "  @Test", "  public void adds() {}", "}")
    (j,) = run_rule("TST002", change({"src/FooTest.java": (java_before, java_after)}))
    assert "subtracts" in j.detail


def test_tst002_threshold_is_configurable():
    after = REFUNDS.replace("def test_partial_refund():\n    assert refund(5) == 5\n", "")
    cfg = Config(rules={"TST002": RuleSettings(options={"high_at": 1})})
    (f,) = run_rule("TST002", change({"tests/test_refunds.py": (REFUNDS, after)}), cfg)
    assert f.severity == Severity.HIGH


# --- TST003 -----------------------------------------------------------------


def test_tst003_skip_markers():
    before = lines("def test_a():", "    pass")
    after = lines("import pytest", "@pytest.mark.skip(reason='flaky')", "def test_a():", "    pass")
    (f,) = run_rule("TST003", change({"tests/test_a.py": (before, after)}))
    assert "1 test skipped or ignored" in f.detail
    assert f.evidence[0].text == "@pytest.mark.skip(reason='flaky')"


def test_tst003_only_markers_are_flagged_and_escalate():
    before = lines("it('a', () => {})")
    after = lines("it.only('a', () => {})")
    (f,) = run_rule("TST003", change({"web/a.test.js": (before, after)}))
    assert ".only" in f.detail
    assert f.severity == Severity.HIGH


def test_tst003_three_skips_escalate():
    before = lines("a", "b", "c")
    after = lines("xit('a')", "xit('b')", "xit('c')")
    (f,) = run_rule("TST003", change({"web/a.spec.js": (before, after)}))
    assert f.severity == Severity.HIGH


def test_tst003_ignores_commented_lines_and_non_test_files():
    before = lines("x = 1")
    commented = lines("# pytest.skip('later')")
    assert run_rule("TST003", change({"tests/test_a.py": (before, commented)})) == []
    prod = lines("pytest.skip('x')")
    assert run_rule("TST003", change({"src/a.py": (before, prod)})) == []


def test_tst003_inline_ignore():
    after = lines("@pytest.mark.skip  # changerisk: ignore TST003")
    assert run_rule("TST003", change({"tests/test_a.py": ("x = 1\n", after)})) == []


# --- TST004 -----------------------------------------------------------------


def test_tst004_fewer_assertions_in_a_surviving_case():
    before = lines(
        "def test_total():",
        "    assert a == 1",
        "    assert b == 2",
        "    assert c == 3",
        "    assert d == 4",
    )
    after = lines("def test_total():", "    assert a == 1")
    (f,) = run_rule("TST004", change({"tests/test_total.py": (before, after)}))
    assert "3 assertions removed, 0 added" in f.detail
    assert len(f.evidence) == 3


def test_tst004_small_drop_is_ignored_and_threshold_configurable():
    before = lines("def test_t():", "    assert 1 == 1", "    assert 2 == 2")
    after = lines("def test_t():", "    assert 1 == 1")
    cs = change({"tests/test_t.py": (before, after)})
    assert run_rule("TST004", cs) == []
    cfg = Config(rules={"TST004": RuleSettings(options={"min_drop": 1})})
    assert len(run_rule("TST004", cs, cfg)) == 1


def test_tst004_tautology_is_flagged():
    before = lines("def test_t():", "    assert compute() == 3")
    after = lines("def test_t():", "    assert True")
    (f,) = run_rule("TST004", change({"tests/test_t.py": (before, after)}))
    assert "cannot fail" in f.detail


def test_tst004_does_not_double_report_when_cases_were_removed():
    before = lines(
        "def test_a():",
        "    assert 1",
        "    assert 2",
        "    assert 3",
        "def test_b():",
        "    assert 4",
    )
    after = lines("def test_a():", "    assert 1")
    assert run_rule("TST004", change({"tests/test_a.py": (before, after)})) == []


# --- TST005 -----------------------------------------------------------------


def big_source(n=30):
    return "".join(f"x{i} = {i}\n" for i in range(n))


def test_tst005_source_changes_without_tests():
    cs = change({"src/billing.py": ("", big_source()), "src/util.py": ("", big_source(5))})
    (f,) = run_rule("TST005", cs)
    assert "35 lines changed across 2 source files" in f.detail
    assert f.paths[0] == "src/billing.py"  # biggest first


def test_tst005_quiet_when_tests_are_touched_or_change_is_small():
    with_tests = change(
        {"src/a.py": ("", big_source()), "tests/test_a.py": ("", "def test_a(): ...\n")}
    )
    assert run_rule("TST005", with_tests) == []
    small = change({"src/a.py": ("", big_source(3))})
    assert run_rule("TST005", small) == []


def test_tst005_deleting_a_test_does_not_count_as_updating_tests():
    cs = change({"src/a.py": ("", big_source()), "tests/test_a.py": ("def test_a(): ...\n", None)})
    assert len(run_rule("TST005", cs)) == 1


def test_tst005_docs_and_generated_do_not_count():
    cs = change({"README.md": ("", big_source(100)), "dist/app.min.js": ("", big_source(100))})
    assert run_rule("TST005", cs) == []


def test_tst005_large_change_is_high():
    cs = change({"src/a.py": ("", big_source(250))})
    assert run_rule("TST005", cs)[0].severity == Severity.HIGH


# --- TST006 -----------------------------------------------------------------


def test_tst006_fail_under_lowered():
    before = lines("[tool.coverage.report]", "fail_under = 90")
    after = lines("[tool.coverage.report]", "fail_under = 70")
    (f,) = run_rule("TST006", change({"pyproject.toml": (before, after)}))
    assert "fail_under lowered from 90 to 70" in f.detail
    assert f.severity == Severity.HIGH  # a 20 point drop


def test_tst006_small_drop_is_medium_and_raise_is_fine():
    low = run_rule("TST006", change({"setup.cfg": ("fail_under = 90\n", "fail_under = 88\n")}))
    assert low[0].severity == Severity.MEDIUM
    assert (
        run_rule("TST006", change({"setup.cfg": ("fail_under = 80\n", "fail_under = 85\n")})) == []
    )


def test_tst006_removed_gate():
    before = lines("addopts = --cov=app --cov-fail-under=85")
    after = lines("addopts = --cov=app")
    (f,) = run_rule("TST006", change({"pytest.ini": (before, after)}))
    assert "removed" in f.detail
    assert f.severity == Severity.HIGH


def test_tst006_jest_thresholds():
    before = lines("branches: 80", "lines: 80")
    after = lines("branches: 60", "lines: 80")
    (f,) = run_rule("TST006", change({"jest.config.js": (before, after)}))
    assert "branches lowered from 80 to 60" in f.detail


def test_tst006_ignores_unrelated_files():
    assert run_rule("TST006", change({"src/a.py": ("lines: 80\n", "lines: 10\n")})) == []


# --- helpers ----------------------------------------------------------------


def test_find_cases_python_and_ruby():
    py = find_cases(
        [(1, "def test_a():"), (3, "    def test_b(self):"), (5, "def helper():")], "python"
    )
    assert py == [(1, "test_a"), (3, "test_b")]
    rb = find_cases([(1, "  it 'does a thing' do")], "ruby")
    assert rb == [(1, "does a thing")]
