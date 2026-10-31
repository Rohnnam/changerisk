"""The Pyodide entry points and the bundle the page loads."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

from changerisk import browser
from changerisk.remote import SourceError

from .test_engine import risky_branch, seeded
from .test_remote import FakeGitHub, pull_routes

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "frontend" / "py" / "changerisk-py.json"


@pytest.fixture
def diff_text(repo):
    seeded(repo)
    risky_branch(repo)
    return repo.git("diff", "main", "feature/speedup")


def run(payload, transport=None):
    return json.loads(
        browser.analyze(json.dumps(payload), transport or (lambda u, h: (404, {}, b"{}")))
    )


# --- analysing ------------------------------------------------------------------


def test_a_pasted_diff_comes_back_as_a_report(diff_text):
    report = run({"source": {"type": "diff", "text": diff_text}})
    assert report["level"] == "critical" and report["range"]["mode"] == "diff"
    assert {f["rule"] for f in report["findings"]} >= {"CFG002", "TST001", "SEC001"}
    assert report["gate"]["fail_on"] == "high"


def test_the_gate_can_be_changed(diff_text):
    report = run({"source": {"type": "diff", "text": diff_text}, "fail_on": "never"})
    assert report["gate"] == {"fail_on": "never", "failed": False, "reason": "The gate is off."}


def test_a_pull_request_goes_through_the_supplied_transport(diff_text):
    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if url.endswith("/pulls/7") and "v3.diff" in headers.get("Accept", ""):
                self.calls.append(url)
                return 200, {}, diff_text.encode()
            return super().__call__(url, headers)

    transport = Transport(pull_routes(diff_text))
    report = run({"source": {"type": "github", "url": "acme/ledger#7"}}, transport)
    assert report["source"]["label"] == "acme/ledger#7" and report["range"]["mode"] == "pr"
    assert {u.split("/")[2] for u in transport.calls} <= {
        "api.github.com",
        "raw.githubusercontent.com",
    }


@pytest.mark.parametrize(
    ("payload", "status", "fragment"),
    [
        ({"source": {"type": "diff", "text": "hello"}}, 400, "does not look like a git diff"),
        ({"source": {"type": "github", "url": "nope"}}, 400, "public GitHub pull request"),
        ({"source": "x"}, 400, "could not be understood"),
        ({}, 400, "could not be understood"),
        (
            {"source": {"type": "diff", "text": "x"}, "fail_on": "sometimes"},
            400,
            "could not be understood",
        ),
    ],
)
def test_problems_come_back_as_data_not_exceptions(payload, status, fragment):
    out = run(payload)
    assert out["status"] == status and fragment in out["error"]


def test_github_errors_keep_their_status():
    out = run({"source": {"type": "github", "url": "acme/ledger#1"}}, lambda u, h: (404, {}, b"{}"))
    assert out["status"] == 404 and "Only public repositories" in out["error"]
    assert json.loads(browser.analyze("{not json"))["status"] == 400


def test_the_page_transport_only_talks_to_github():
    fetch = browser.browser_transport()
    for url in ("https://evil.example/x", "http://api.github.com/x", "file:///etc/passwd"):
        with pytest.raises(SourceError, match="Refusing"):
            fetch(url, {})


# --- exporting ------------------------------------------------------------------------


def test_exports_render_from_the_report_the_page_holds(diff_text):
    report_json = browser.analyze(json.dumps({"source": {"type": "diff", "text": diff_text}}))
    assert browser.render("markdown", report_json).startswith("<!-- changerisk-report -->")
    assert json.loads(browser.render("sarif", report_json))["version"] == "2.1.0"
    assert json.loads(browser.render("json", report_json))["level"] == "critical"
    assert "RISK  CRITICAL" in browser.render("text", report_json)


def test_export_errors_are_plain():
    with pytest.raises(ValueError, match="format must be one of"):
        browser.render("html", "{}")
    with pytest.raises(ValueError, match="does not look like"):
        browser.render("json", '{"x": 1}')
    with pytest.raises(ValueError, match="does not look like"):
        browser.render("json", "not json")


# --- the bundle ---------------------------------------------------------------------------


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_bundle", ROOT / "scripts" / "build_browser_bundle.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_committed_bundle_is_what_the_script_produces():
    assert BUNDLE.read_text(encoding="utf-8") == load_builder().render(), (
        "frontend/py/changerisk-py.json is stale; run python scripts/build_browser_bundle.py"
    )


def test_the_bundle_leaves_out_everything_that_needs_a_server_or_a_disk():
    files = json.loads(BUNDLE.read_text(encoding="utf-8"))["files"]
    for name in ("server", "hosted", "cli", "store", "webassets", "github", "__main__"):
        assert f"changerisk/{name}.py" not in files
    assert "changerisk/reports/html.py" not in files
    assert {"changerisk/browser.py", "changerisk/remote.py", "changerisk/engine.py"} <= set(files)
    assert not any(
        "http.server" in text or "ThreadingHTTPServer" in text for text in files.values()
    )


def test_the_bundle_works_on_its_own(tmp_path, diff_text):
    """Unpack it into an empty directory and run an analysis with nothing else on the path.

    This is what the page does, so it catches a bundled module importing one that was left out.
    """
    files = json.loads(BUNDLE.read_text(encoding="utf-8"))["files"]
    for rel, text in files.items():
        target = tmp_path / "pkg" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    (tmp_path / "diff.txt").write_text(diff_text, encoding="utf-8")
    script = (
        "import sys, json; sys.path.insert(0, sys.argv[1])\n"
        "import changerisk.browser as b\n"
        "text = open(sys.argv[2], encoding='utf-8').read()\n"
        "out = json.loads(b.analyze(json.dumps({'source': {'type': 'diff', 'text': text}})))\n"
        "assert out['level'] == 'critical', out\n"
        "assert b.render('markdown', json.dumps(out)).startswith('<!--')\n"
        "print('ok', out['score'])\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", script, str(tmp_path / "pkg"), str(tmp_path / "diff.txt")],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("ok")
