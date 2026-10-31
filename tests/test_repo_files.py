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


def test_the_container_is_set_up_for_production():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in text and "--uid 1000" in text, (
        "run unprivileged, as uid 1000 like Hugging Face"
    )
    assert "EXPOSE 7860" in text and "HEALTHCHECK" in text and "/api/health" in text
    assert '"--hosted"' in text and '"0.0.0.0"' in text
    ignore = (ROOT / ".dockerignore").read_text(encoding="utf-8").split()
    assert {".git", ".venv", "tests", "examples"} <= set(ignore)


def test_the_hugging_face_space_files_are_consistent():
    space = ROOT / "deploy" / "hf-space"
    readme = (space / "README.md").read_text(encoding="utf-8")
    front = yaml.safe_load(readme.split("---")[1])
    assert front["sdk"] == "docker" and front["app_port"] == 7860
    assert len(front["short_description"]) <= 60
    dockerfile = (space / "Dockerfile").read_text(encoding="utf-8")
    assert "USER app" in dockerfile and "EXPOSE 7860" in dockerfile and "--hosted" in dockerfile
    assert "CHANGERISK_TRUSTED_PROXIES" in dockerfile and "CHANGERISK_FRAME_ANCESTORS" in dockerfile
    assert "github.com/Rohnnam/changerisk/archive/${CHANGERISK_REF}.zip" in dockerfile


def test_documented_settings_are_the_ones_the_code_reads():
    deploy = (ROOT / "docs" / "DEPLOY.md").read_text(encoding="utf-8")
    code = (ROOT / "src" / "changerisk" / "hosted.py").read_text(encoding="utf-8")
    remote = (ROOT / "src" / "changerisk" / "remote.py").read_text(encoding="utf-8")
    read = set(re.findall(r'"(CHANGERISK_[A-Z_]+|GITHUB_TOKEN)"', code + remote))
    documented = set(re.findall(r"`(CHANGERISK_[A-Z_]+|GITHUB_TOKEN)`", deploy))
    assert read <= documented, f"undocumented settings: {read - documented}"
    build_args = {
        "CHANGERISK_REF"
    }  # a Docker build argument in the Space image, not read by the app
    assert documented - build_args <= read, (
        f"documented but unused: {documented - build_args - read}"
    )
