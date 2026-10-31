"""Hostile and awkward input must stay cheap. A public server cannot be stalled by one diff.

The thresholds are generous (the real costs are a tenth of them or less) so these only fail when
something goes from linear to quadratic, which is the failure that matters.
"""

import time

import pytest

from changerisk.config import Config
from changerisk.engine import analyze_changes
from changerisk.remote import MAX_LINE_CHARS, changes_from_diff

LINES = 100


def new_file_diff(path, line):
    body = "".join(f"+{line}\n" for _ in range(LINES))
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{LINES} @@\n{body}"
    )


def analysis_seconds(path, line):
    start = time.perf_counter()
    analyze_changes(changes_from_diff(new_file_diff(path, line)), Config(), None)
    return time.perf_counter() - start


def test_long_runs_of_word_characters_are_not_quadratic():
    # A minified bundle looks like this. It once took about 23 seconds for these 100 lines.
    assert analysis_seconds("src/bundle.js", "a" * 4000) < 3
    assert analysis_seconds("src/app.py", "api_key_" * 500) < 3
    assert analysis_seconds(".env.production", "A=" + "b" * 4000) < 3


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("config/app.yml", "key: " + "a: " * 1300),
        ("config/app.yml", "k" + ":" * 3990),
        ("requirements.txt", "a" + " ," * 1990),
        ("requirements.txt", "pkg ==" + "1." * 1990),
        ("pyproject.toml", '"pkg' + ">=" * 1990),
        ("package.json", '"a": "' + "^" * 3980),
        (".github/workflows/ci.yml", "uses: " + "a/" * 1990 + "@"),
        ("db/migrations/0001.sql", "ALTER TABLE " + "x " * 1990 + "DROP"),
        ("db/migrations/0001.sql", "DELETE FROM " + "a" * 3980),
        ("tests/test_a.py", "def test" + "_" * 3990),
        ("web/a.test.ts", "it" + ".a" * 1990),
        ("src/a.py", '.execute("' + "select " * 560 + '" %'),
        ("src/a.py", "password = '" + "a" * 3980),
        ("src/a.py", "-----BEGIN " + "RSA " * 990),
    ],
)
def test_hostile_line_shapes_stay_cheap(path, line):
    assert analysis_seconds(path, line) < 4


def test_a_maximum_size_diff_of_ordinary_code_is_quick():
    line = "value = compute(alpha, beta, gamma) + other_function(delta, epsilon) # " + "x" * 120
    text = new_file_diff("src/big.py", line).replace(f"@@ -0,0 +1,{LINES} @@", "@@ -0,0 +1,9000 @@")
    text += "".join(f"+{line}\n" for _ in range(9000 - LINES))
    start = time.perf_counter()
    analyze_changes(changes_from_diff(text), Config(), None)
    assert time.perf_counter() - start < 10


def test_lines_are_cut_before_any_rule_sees_them():
    text = (
        "diff --git a/src/a.py b/src/a.py\nnew file mode 100644\n--- /dev/null\n+++ b/src/a.py\n"
        "@@ -0,0 +1,5 @@\n" + ("+" + "z" * 100_000 + "\n") * 5
    )
    cs = changes_from_diff(text)
    assert all(len(ln.text) <= MAX_LINE_CHARS for f in cs.files for ln in f.added_lines())


def test_the_time_budget_stops_a_slow_analysis_and_says_so():
    cs = changes_from_diff(new_file_diff("config/app.yml", "debug: true"))
    report = analyze_changes(cs, Config(), None, deadline=time.monotonic() - 1)
    assert report.findings == []
    assert any("time limit" in n for n in report.notes)


def test_binary_and_empty_hunks_do_not_break_the_hosted_path():
    text = (
        "diff --git a/logo.png b/logo.png\nnew file mode 100644\nBinary files /dev/null and b/logo.png differ\n"
        "diff --git a/run.sh b/run.sh\nold mode 100644\nnew mode 100755\n"
    )
    report = analyze_changes(changes_from_diff(text), Config(), None)
    assert len(report.files) == 2 and report.score == 0
