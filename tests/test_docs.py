import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]


def load_generator():
    spec = importlib.util.spec_from_file_location(
        "gen_rules_doc", ROOT / "scripts" / "gen_rules_doc.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rules_reference_matches_the_registry():
    gen = load_generator()
    assert (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8") == gen.render(), (
        "docs/RULES.md is stale; run python scripts/gen_rules_doc.py"
    )


def test_rules_reference_covers_every_rule():
    from changerisk.rules import load_all
    from changerisk.rules.base import all_rules

    load_all()
    text = (ROOT / "docs" / "RULES.md").read_text(encoding="utf-8")
    for rule in all_rules():
        assert f"### {rule.info.id}" in text


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.name)
def test_relative_links_resolve(path):
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
        if re.match(r"[a-z]+:", target):
            continue
        assert (path.parent / target).exists(), (
            f"{path.name} links to {target}, which does not exist"
        )


def test_readme_documents_the_main_commands_and_the_rule_count():
    from changerisk.rules import load_all
    from changerisk.rules.base import all_rules

    load_all()
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for command in (
        "changerisk analyze",
        "changerisk init",
        "changerisk serve",
        "changerisk rules",
    ):
        assert command in readme
    assert f"{len(all_rules())} rules in ten areas" in readme


def test_no_emoji_or_placeholder_text_in_the_docs():
    emoji = re.compile("[\U0001f300-\U0001faff☀-➿]")
    for path in DOCS:
        text = path.read_text(encoding="utf-8")
        assert not emoji.search(text), path.name
        assert "lorem ipsum" not in text.lower() and "TODO" not in text, path.name
