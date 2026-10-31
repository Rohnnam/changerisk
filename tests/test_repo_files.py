"""The repository's own CI files, held to the standards the tool enforces on others."""

import re
import tomllib
from pathlib import Path

import pytest
import yaml

import changerisk
from changerisk.models import Severity

from .helpers import change, run_rule

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
ACTION = ROOT / "action.yml"


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(doc: dict):
    return doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as the boolean True


def steps_of(doc: dict):
    if "jobs" in doc:
        for job in doc["jobs"].values():
            yield from job.get("steps", [])
    else:
        yield from doc["runs"]["steps"]


def test_there_are_workflows():
    assert {p.name for p in WORKFLOWS} >= {"ci.yml", "changerisk.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_structure(path):
    doc = load(path)
    assert doc["name"] and triggers(doc)
    assert "permissions" in doc, "declare permissions at the top so the default token is not broad"
    assert "write-all" not in path.read_text(encoding="utf-8")
    for name, job in doc["jobs"].items():
        assert "runs-on" in job, name
        for step in job["steps"]:
            assert ("uses" in step) ^ ("run" in step), step


@pytest.mark.parametrize("path", [*WORKFLOWS, ACTION], ids=lambda p: p.name)
def test_steps_are_pinned_and_do_not_interpolate_untrusted_input(path):
    doc = load(path)
    for step in steps_of(doc):
        uses = step.get("uses")
        if uses and not uses.startswith("./"):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@v?\d[\w.]*", uses), (
                f"{uses} should be pinned to a version"
            )
        script = step.get("run", "")
        assert not re.search(r"\$\{\{\s*(inputs|github\.event|github\.head_ref)", script), (
            "pass values through env vars, not into the script text"
        )
    assert "pull_request_target" not in path.read_text(encoding="utf-8")


def test_the_action_is_complete():
    doc = load(ACTION)
    assert doc["runs"]["using"] == "composite"
    for key in ("name", "description", "inputs", "outputs"):
        assert doc[key]
    for name, spec in doc["inputs"].items():
        assert spec["description"], name
        assert "default" in spec, name
    for name, spec in doc["outputs"].items():
        assert spec["description"] and spec["value"].startswith("${{ steps."), name
    for step in doc["runs"]["steps"]:
        if "run" in step:
            assert step["shell"] == "bash"
    ids = {s["id"] for s in doc["runs"]["steps"] if "id" in s}
    referenced = set(re.findall(r"steps\.(\w+)\.outputs", ACTION.read_text(encoding="utf-8")))
    assert referenced <= ids


def test_every_action_input_the_workflow_uses_exists():
    action_inputs = set(load(ACTION)["inputs"])
    for step in steps_of(load(ROOT / ".github" / "workflows" / "changerisk.yml")):
        if step.get("uses") == "./":
            assert set(step.get("with", {})) <= action_inputs


def test_the_cli_flags_the_action_passes_exist():
    from changerisk import cli

    parser = cli.build_parser()
    ci = next(a for a in parser._subparsers._group_actions[0].choices.items() if a[0] == "ci")[1]
    known = {opt for action in ci._actions for opt in action.option_strings}
    script = next(s["run"] for s in load(ACTION)["runs"]["steps"] if s.get("id") == "run")
    used = set(re.findall(r"--[a-z][a-z-]+", script))
    assert used <= known, used - known


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_our_own_workflows_pass_our_own_pipeline_rules(path):
    rel = f".github/workflows/{path.name}"
    cs = change({rel: (None, path.read_text(encoding="utf-8"))})
    weak = run_rule("CI002", cs)
    assert weak == [], [f.detail for f in weak]
    widened = run_rule("CI003", cs)
    # The only thing allowed to show up is the deliberate pull-requests: write on the dogfood workflow.
    assert all(f.severity <= Severity.MEDIUM for f in widened), [f.detail for f in widened]
    assert all("write permission" in f.detail and "moving branch" not in f.detail for f in widened)


def test_version_is_in_one_place_and_agrees():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["version"] == changerisk.__version__
