"""The Hugging Face Space: two generated files that pin the dashboard to one commit."""

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture(scope="module")
def space():
    spec = importlib.util.spec_from_file_location(
        "build_space", ROOT / "scripts" / "build_space.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def index(space):
    return space.build_index(space.assets_base(SHA, None))


def config_of(html):
    block = re.search(
        r'<script type="application/json" id="changerisk-config">(.*?)</script>', html
    )
    return json.loads(block.group(1))["browser"]


def test_every_address_is_pinned_to_the_commit(index):
    base = f"https://cdn.jsdelivr.net/gh/Rohnnam/changerisk@{SHA}/frontend/"
    local = re.findall(r'(?:href|src)="((?:css|js|img)/[^"]+)"', index)
    assert local == [], f"still relative: {local}"
    for url in re.findall(r'(?:href|src)="(https://[^"]+)"', index):
        assert url.startswith(base), url
    cfg = config_of(index)
    assert cfg["worker"] == base + "js/browser-worker.js"
    assert cfg["bundle"] == base + "py/changerisk-py.json"
    assert cfg["pyodide"].startswith("https://cdn.jsdelivr.net/pyodide/v") and cfg[
        "pyodide"
    ].endswith("/")


def test_what_the_page_loads_exists_in_the_repository(index):
    base = f"https://cdn.jsdelivr.net/gh/Rohnnam/changerisk@{SHA}/frontend/"
    paths = [
        u[len(base) :] for u in re.findall(r'(?:href|src)="(' + re.escape(base) + r'[^"]+)"', index)
    ]
    assert "js/main.js" in paths and "css/tokens.css" in paths
    for rel in paths + ["js/browser-worker.js", "py/changerisk-py.json"]:
        assert (ROOT / "frontend" / rel).is_file(), rel


def test_the_page_has_a_strict_policy_and_runs_no_inline_code(index):
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', index).group(1)
    assert "'unsafe-inline'" not in policy and "default-src 'none'" in policy
    assert "'unsafe-eval'" not in policy and "'wasm-unsafe-eval'" in policy  # WebAssembly only
    assert "worker-src blob:" in policy
    connect = re.search(r"connect-src ([^;]+)", policy).group(1).split()
    assert {"https://api.github.com", "https://raw.githubusercontent.com"} <= set(connect)
    assert not [h for h in connect if "*" in h or h in ("https:", "http:")]
    scripts = re.findall(r"<script([^>]*)>", index)
    inline = [a for a in scripts if "src=" not in a]
    assert all('type="application/json"' in a for a in inline), inline
    assert 'name="referrer" content="no-referrer"' in index


def test_the_worker_is_a_classic_script(index):
    """It is started from a Blob, where import statements do not work."""
    text = (ROOT / "frontend" / "js" / "browser-worker.js").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|export)\s", text, re.M)
    assert "importScripts" in text


def test_a_commit_is_required_unless_serving_locally(space):
    for bad in (None, "main", "v1", SHA[:7], SHA.upper()):
        with pytest.raises(SystemExit):
            space.assets_base(bad, None)
    assert space.assets_base(None, "http://127.0.0.1:8123") == "http://127.0.0.1:8123/"


def test_the_readme_describes_a_static_space(space):
    front = yaml.safe_load(space.build_readme().split("---")[1])
    assert front["sdk"] == "static" and len(front["short_description"]) <= 60
    assert "app_port" not in front
