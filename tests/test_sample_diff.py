"""The example diff behind "Load an example" in the hosted dashboard."""

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


def sample_text() -> str:
    js = SAMPLE.read_text(encoding="utf-8")
    lines = json.loads(re.search(r"const LINES = (\[.*?\n\]);", js, re.S).group(1))
    return "\n".join(lines).replace("__STRIPE_KEY__", FAKE_KEY) + "\n"


def test_the_example_tells_a_complete_story():
    report = analyze_changes(changes_from_diff(sample_text()), Config(), None)
    assert report.level == Level.CRITICAL and report.gate_failed
    rules = {f.rule_id for f in report.findings}
    # the two cases the project is about, plus one from each of several other areas
    assert {
        "CFG002",
        "CFG003",
        "TST001",
        "SEC001",
        "SEC003",
        "DEP002",
        "DEP003",
        "CI002",
        "DB002",
        "API001",
    } <= rules
    assert len(report.files) == 6
    assert FAKE_KEY not in json.dumps(report.to_dict())  # the key is masked like any other


def test_no_secret_shaped_string_is_committed_in_the_page_script():
    text = SAMPLE.read_text(encoding="utf-8")
    assert "sk_live_" not in text and "AKIA" not in text
    assert "__STRIPE_KEY__" in text and "'sk_' + 'live_'" in text


def test_the_committed_file_is_what_the_generator_produces():
    spec = importlib.util.spec_from_file_location(
        "gen_sample_diff", ROOT / "scripts" / "gen_sample_diff.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert SAMPLE.read_text(encoding="utf-8") == module.render(module.build_diff()), (
        "frontend/js/sample-diff.js is stale; run python scripts/gen_sample_diff.py"
    )


def test_the_example_is_well_under_the_hosted_size_limit():
    assert len(sample_text().encode()) < 8 * 1024


@pytest.mark.parametrize(
    "needle", ["diff --git a/config/production.yml", "deleted file mode", "new file mode"]
)
def test_the_example_covers_modified_deleted_and_added_files(needle):
    assert needle in sample_text()
