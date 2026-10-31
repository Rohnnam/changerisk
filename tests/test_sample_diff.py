"""The built-in examples the hosted dashboard offers on its first screen."""

import importlib.util
import json
import re
from pathlib import Path

import pytest

from changerisk.config import Config
from changerisk.engine import analyze_changes
from changerisk.models import Level
from changerisk.remote import changes_from_diff

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "frontend" / "js" / "sample-diff.js"
FAKE_KEY = "sk_" + "live_" + "51Hq7LKd2eZvKYlo2C0xv9nTq8RbW3mA"


def source() -> str:
    return SAMPLE.read_text(encoding="utf-8")


def diffs() -> dict[str, str]:
    raw = json.loads(re.search(r"const DIFFS = (\{.*?\n\});", source(), re.S).group(1))
    return {
        name: "\n".join(lines).replace("__STRIPE_KEY__", FAKE_KEY) + "\n"
        for name, lines in raw.items()
    }


def cards() -> list[dict[str, str]]:
    """The EXAMPLES entries as written in the script: id, label, title, summary, expect."""
    found = re.findall(
        r'id: "(\w+)",\n\s+label: "(.*?)",\n\s+title: "(.*?)",\n\s+summary: "(.*?)",\n\s+expect: "(\w+)"',
        source(),
    )
    keys = ("id", "label", "title", "summary", "expect")
    return [dict(zip(keys, row, strict=True)) for row in found]


def analyse(name: str):
    return analyze_changes(changes_from_diff(diffs()[name]), Config(), None)


def test_there_are_three_examples_that_span_the_range():
    assert [c["id"] for c in cards()] == ["tidy", "review", "critical"]
    assert [c["expect"] for c in cards()] == ["low", "moderate", "critical"]
    assert set(diffs()) == {c["id"] for c in cards()}


@pytest.mark.parametrize("card", cards(), ids=lambda c: c["id"])
def test_each_example_scores_as_its_card_says(card):
    report = analyse(card["id"])
    assert report.level == Level.parse(card["expect"]), (card["id"], report.score)


def test_the_gate_story_differs_between_them():
    assert not analyse("tidy").gate_failed
    assert not analyse(
        "review"
    ).gate_failed  # moderate: passes the default gate, with findings to read
    assert analyse("critical").gate_failed


def test_the_critical_example_tells_a_complete_story():
    report = analyse("critical")
    rules = {f.rule_id for f in report.findings}
    # the two cases the project is about, plus one from each of several other areas
    assert {
        "CFG002", "CFG003", "TST001", "SEC001", "SEC003",
        "DEP002", "DEP003", "CI002", "DB002", "API001",
    } <= rules  # fmt: skip
    assert len(report.files) == 6
    assert FAKE_KEY not in json.dumps(report.to_dict())  # the key is masked like any other


def test_the_middle_example_is_about_edits_that_add_up():
    rules = {f.rule_id for f in analyse("review").findings}
    assert {"CFG001", "DEP003", "TST002"} <= rules
    assert not rules & {"SEC001", "DB002", "CFG003"}  # nothing alarming on its own


def test_the_tidy_example_notes_the_payments_folder_and_nothing_else():
    assert {f.rule_id for f in analyse("tidy").findings} == {"SEC002"}


def test_no_secret_shaped_string_is_committed_in_the_page_script():
    text = source()
    assert "sk_live_" not in text and "AKIA" not in text
    assert "__STRIPE_KEY__" in text and "'sk_' + 'live_'" in text


def test_the_committed_file_is_what_the_generator_produces():
    spec = importlib.util.spec_from_file_location(
        "gen_sample_diff", ROOT / "scripts" / "gen_sample_diff.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert source() == module.render(module.build_all()), (
        "frontend/js/sample-diff.js is stale; run python scripts/gen_sample_diff.py"
    )


def test_the_examples_are_well_under_the_hosted_size_limit():
    assert all(len(text.encode()) < 8 * 1024 for text in diffs().values())


@pytest.mark.parametrize(
    "needle", ["diff --git a/config/production.yml", "deleted file mode", "new file mode"]
)
def test_the_critical_example_covers_modified_deleted_and_added_files(needle):
    assert needle in diffs()["critical"]
