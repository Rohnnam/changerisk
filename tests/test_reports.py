import json

import pytest

from changerisk import engine
from changerisk.reports import FORMATS, annotate, markdown, render, text

from .test_engine import risky_branch, seeded


@pytest.fixture
def report(repo):
    seeded(repo)
    risky_branch(repo)
    return engine.analyze(
        repo.root, base="main", head="feature/speedup", use_history=False, include_diffs="flagged"
    )


@pytest.fixture
def clean_report(repo):
    seeded(repo)
    repo.branch("docs/typo")
    repo.write("README.md", "# ledger\n\nfixed\n")
    repo.commit("typo")
    return engine.analyze(repo.root, base="main", head="docs/typo", use_history=False)


# --- text -------------------------------------------------------------------


def test_text_report_is_ascii_and_has_the_main_sections(report):
    out = text.render(report)
    out.encode("ascii")  # must survive any Windows code page
    for needle in (
        "RISK  CRITICAL",
        "gate FAILED",
        "Why this needs extra testing",
        "Test plan",
        "Riskiest files",
    ):
        assert needle in out
    assert "+30.0" in out and "[CRIT]" in out and "[MED]" in out
    assert "1 commit)" in out


def test_text_report_colour_is_optional(report):
    assert "\x1b[" not in text.render(report, color=False)
    assert "\x1b[" in text.render(report, color=True)


def test_text_report_wraps_to_width(report):
    out = text.render(report, width=70)
    assert max(len(line) for line in out.splitlines()) <= 72


def test_text_verbose_shows_everything(report):
    brief, full = text.render(report), text.render(report, verbose=True)
    assert "Why it matters:" in full and "Why it matters:" not in brief
    assert "more (use --verbose" in brief and "more (use --verbose" not in full


def test_header_pluralises_file_counts(clean_report):
    assert "(1 file, +" in text.render(clean_report)
    assert "1 file," in markdown.render(clean_report)


def test_text_for_clean_change(clean_report):
    out = text.render(clean_report)
    assert "RISK  LOW" in out and "gate passed" in out and "Why this needs" not in out


# --- markdown ---------------------------------------------------------------


def test_markdown_has_marker_sections_and_checklist(report):
    out = markdown.render(report, link="https://example.test/run/1")
    assert out.startswith(markdown.MARKER)
    assert "## ChangeRisk: Critical risk (" in out
    assert "### Why this needs extra testing" in out and "### Test plan" in out
    assert "- [ ] " in out and "<details>" in out
    assert "[ChangeRisk 0.1.0](https://example.test/run/1)" in out


def test_markdown_without_marker_for_step_summary(report):
    assert markdown.MARKER not in markdown.render(report, marker=False)


def test_markdown_escapes_table_cells_and_backticks():
    assert markdown._cell("a|b") == "a\\|b"
    assert markdown._code("plain") == "`plain`"
    assert markdown._code("a`b") == "``a`b``"


def test_markdown_is_capped_for_github(report):
    report.findings[0].detail = "x" * 70000
    out = markdown.render(report)
    assert len(out) <= markdown.COMMENT_LIMIT
    assert "truncated" in out


def test_markdown_clean_change(clean_report):
    out = markdown.render(clean_report)
    assert "Low risk (0/100)" in out and "Why this needs extra testing" not in out


# --- json / sarif / annotations ---------------------------------------------


def test_json_round_trips_and_has_schema(report):
    data = json.loads(render(report, "json"))
    assert data["schema"] == "changerisk.report/1"
    assert data["score"] == report.score and len(data["findings"]) == len(report.findings)


def test_annotations_format_and_caps(report):
    out = annotate.annotations(report)
    lines = out.splitlines()
    assert all(line.startswith(("::error ", "::warning ", "::notice ")) for line in lines)
    assert any("file=config/production.yml,line=4" in line for line in lines)
    assert sum(line.startswith("::error") for line in lines) <= annotate.PER_KIND


def test_annotation_escaping():
    assert annotate._escape_data("a%b\nc") == "a%25b%0Ac"
    assert annotate._escape_prop("a:b,c") == "a%3Ab%2Cc"


def test_annotations_cap_each_kind_at_ten(report):
    template = report.findings[0]
    report.findings = [template] * 25
    assert len(annotate.annotations(report).splitlines()) == annotate.PER_KIND


def test_annotations_do_not_point_at_removed_lines(report):
    deleted = next(f for f in report.findings if f.rule_id == "TST001")
    line = next(ln for ln in annotate.annotations(report).splitlines() if "Test file deleted" in ln)
    assert "line=" not in line  # only old-side evidence, so pin to the file without a line
    assert deleted.evidence[0].side == "old"


def test_sarif_is_valid_shape(report):
    doc = json.loads(render(report, "sarif"))
    run = doc["runs"][0]
    assert doc["version"] == "2.1.0"
    ids = {r["id"] for r in run["tool"]["driver"]["rules"]}
    assert {res["ruleId"] for res in run["results"]} == ids
    assert all(res["level"] in ("error", "warning", "note") for res in run["results"])
    located = [r for r in run["results"] if "locations" in r]
    assert located and "uri" in located[0]["locations"][0]["physicalLocation"]["artifactLocation"]


def test_unknown_format_is_rejected(report):
    with pytest.raises(ValueError, match="unknown format"):
        render(report, "yaml")
    assert set(FORMATS) == {"text", "markdown", "json", "html", "github", "sarif"}
