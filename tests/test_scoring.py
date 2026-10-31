import random

import pytest

from changerisk.config import Config, RuleSettings
from changerisk.explain import build_test_plan, category_breakdown, verdict
from changerisk.models import Finding, Level, Severity
from changerisk.scoring import POINTS, apply_points, level_for, score, value_for


def finding(rule="CFG001", sev=Severity.MEDIUM, category="config", path="a.yml", tests=()):
    return Finding(
        rule_id=rule, category=category, title=f"{rule} title", severity=sev, detail="d",
        paths=[path], test_focus=list(tests),
    )  # fmt: skip


def scored(findings, config=None):
    apply_points(findings, config or Config())
    return score(findings)


def test_value_curve_is_zero_based_monotonic_and_bounded():
    assert value_for(0) == 0
    values = [value_for(p) for p in range(0, 400, 5)]
    assert values == sorted(values)
    assert max(values) <= 100
    assert value_for(8) == 18 and value_for(16) == 33 and value_for(30) == 53


def test_level_bands():
    assert [level_for(v) for v in (0, 24, 25, 49, 50, 74, 75, 100)] == [
        Level.LOW, Level.LOW, Level.MODERATE, Level.MODERATE,
        Level.HIGH, Level.HIGH, Level.CRITICAL, Level.CRITICAL,
    ]  # fmt: skip


def test_repeated_hits_of_one_rule_decay():
    fs = [finding(path=f"{i}.yml") for i in range(3)]
    result = scored(fs)
    assert [f.points for f in fs] == [8.0, 4.0, 2.0]
    assert result.points == 14.0


def test_different_rules_do_not_decay_each_other():
    fs = [finding("CFG001"), finding("TST001", Severity.HIGH, "tests")]
    assert scored(fs).points == POINTS[Severity.MEDIUM] + POINTS[Severity.HIGH]


def test_points_shown_on_findings_add_up_to_the_total():
    rng = random.Random(7)
    sevs = list(Severity)
    fs = [finding(f"R{rng.randint(1, 4)}", rng.choice(sevs)) for _ in range(25)]
    result = scored(fs)
    assert sum(f.points for f in fs) == pytest.approx(result.points)


def test_weight_scales_points_and_zero_silences():
    fs = [finding()]
    scored(fs, Config(rules={"CFG001": RuleSettings(weight=2.0)}))
    assert fs[0].points == 16.0
    fs = [finding()]
    assert scored(fs, Config(rules={"CFG001": RuleSettings(weight=0)})).value == 0


def test_adding_a_finding_never_lowers_the_score():
    rng = random.Random(3)
    sevs = list(Severity)
    fs: list[Finding] = []
    previous = 0
    for _ in range(40):
        fs.append(finding(f"R{rng.randint(1, 6)}", rng.choice(sevs)))
        current = scored(fs).value
        assert current >= previous
        previous = current


def test_single_critical_is_high_on_points_alone():
    result = scored([finding("SEC001", Severity.CRITICAL, "security")])
    assert result.level == Level.HIGH and result.floor_note is None


def test_floor_lifts_level_and_score_together():
    fs = [finding("SEC001", Severity.CRITICAL, "security")]
    result = scored(fs, Config(rules={"SEC001": RuleSettings(weight=0.3)}))
    assert result.level == Level.HIGH
    assert result.value == 50
    assert "Raised to high because of a critical finding (SEC001)" in result.floor_note

    fs = [finding("TST001", Severity.HIGH, "tests")]
    result = scored(fs, Config(rules={"TST001": RuleSettings(weight=0.5)}))
    assert result.level == Level.MODERATE and result.value == 25


def test_no_findings_is_low_zero():
    result = scored([])
    assert (result.value, result.level, result.floor_note) == (0, Level.LOW, None)


# --- explain ----------------------------------------------------------------


def test_verdict_wording_by_level():
    fs = [finding("TST001", Severity.HIGH, "tests"), finding("CFG001")]
    apply_points(fs, Config())
    fs[0].title, fs[1].title = "Test file deleted", "Configuration changed"
    text = verdict(Level.HIGH, fs, 4)
    assert text.startswith("This change needs extra testing")
    assert "test file deleted and configuration changed" in text
    assert verdict(Level.LOW, [], 3).startswith("No risky patterns found in 3 changed files.")
    assert verdict(Level.LOW, [], 0) == "No changes to analyse."
    assert (
        verdict(Level.LOW, [], 0, ignored=2)
        == "All 2 changed files are excluded by paths.ignore, so there is nothing to analyse."
    )
    assert "1 changed file is excluded" in verdict(Level.LOW, [], 0, ignored=1)


def test_verdict_keeps_acronyms_intact():
    f = finding("API001", Severity.MEDIUM, "interfaces")
    f.title = "API contract changed"
    apply_points([f], Config())
    assert "API contract changed" in verdict(Level.MODERATE, [f], 1)


def test_test_plan_merges_duplicates_and_orders_by_priority():
    a = finding("TST001", Severity.HIGH, "tests", tests=["Run the old file", "Check coverage"])
    b = finding("CFG001", Severity.MEDIUM, "config", tests=["Check coverage", "Start the service"])
    c = finding("COD003", Severity.LOW, "code", tests=["Remove each suppression"])
    apply_points([a, b, c], Config())
    steps, hidden = build_test_plan([c, b, a])
    assert hidden == 0
    assert [s.text for s in steps] == [
        "Run the old file", "Check coverage", "Start the service", "Remove each suppression",
    ]  # fmt: skip
    shared = next(s for s in steps if s.text == "Check coverage")
    assert shared.priority == 1 and shared.rules == ["TST001", "CFG001"]


def test_test_plan_is_capped():
    fs = [
        finding(f"R{i}", Severity.MEDIUM, tests=[f"step {i}-{j}" for j in range(3)])
        for i in range(8)
    ]
    apply_points(fs, Config())
    steps, hidden = build_test_plan(fs)
    assert len(steps) == 14 and hidden == 10


def test_category_breakdown_orders_by_points():
    fs = [
        finding("CFG001"),
        finding("TST001", Severity.HIGH, "tests"),
        finding("CFG002", Severity.HIGH),
    ]
    apply_points(fs, Config())
    rows = category_breakdown(fs)
    assert [r["id"] for r in rows] == ["config", "tests"]
    assert (
        rows[0]["points"] == 24.0 and rows[0]["findings"] == 2 and rows[0]["top_severity"] == "high"
    )
