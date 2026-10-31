"""The dashboard bundler and the standalone HTML report."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from changerisk import engine, scoring
from changerisk.models import RiskReport
from changerisk.reports import html as html_report
from changerisk.webassets import BundleError, bundle_js, inline_page, web_dir

from .test_engine import risky_branch, seeded

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run_node(*args: str, stdin: str | None = None) -> str:
    out = subprocess.run(
        [NODE, *args], input=stdin, capture_output=True, text=True, check=False, encoding="utf-8"
    )
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.fixture
def report(repo):
    seeded(repo)
    risky_branch(repo)
    return engine.analyze(repo.root, base="main", head="feature/speedup", use_history=False)


# --- bundler -----------------------------------------------------------------


def make_site(tmp_path, files):
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return tmp_path


def test_modules_are_ordered_dependencies_first(tmp_path):
    root = make_site(
        tmp_path,
        {
            "js/main.js": "import { add } from './math.js';\nimport { label } from './views/label.js';\nconsole.log(label(add(1, 2)));\n",
            "js/math.js": "export function add(a, b) { return a + b; }\n",
            "js/views/label.js": "import { add } from '../math.js';\nexport const label = (n) => `n=${n + add(0, 0)}`;\n",
        },
    )
    js = bundle_js(root)
    assert js.index("// js/math.js") < js.index("// js/views/label.js") < js.index("// js/main.js")
    assert "import " not in js and not re.search(r"^\s*export\s", js, re.M)


@needs_node
def test_bundled_code_runs_and_keeps_module_scopes_apart(tmp_path):
    root = make_site(
        tmp_path,
        {
            "js/main.js": "import { a } from './a.js';\nimport { b } from './b.js';\nconsole.log(a(), b());\n",
            "js/a.js": "const secret = 'a';\nexport function a() { return secret; }\n",
            "js/b.js": "const secret = 'b';\nexport async function bee() {}\nexport function b() { return secret; }\n",
        },
    )
    assert run_node(stdin=bundle_js(root)).strip() == "a b"


def test_unsupported_syntax_is_refused(tmp_path):
    root = make_site(tmp_path, {"js/main.js": "export default function () {}\n"})
    with pytest.raises(BundleError, match="unsupported"):
        bundle_js(root)
    root2 = make_site(
        tmp_path / "two",
        {"js/main.js": "import { a as b } from './x.js';\n", "js/x.js": "export const a = 1;\n"},
    )
    with pytest.raises(BundleError, match="renames"):
        bundle_js(root2)


@needs_node
def test_the_real_frontend_bundles_and_parses():
    js = bundle_js(web_dir())
    assert js.count("const __m_") >= 20
    assert not re.search(r"^(import|export)\b", js, re.M)
    probe = Path(__file__).with_name("_bundle_probe.js")
    probe.write_text(js, encoding="utf-8")
    try:
        run_node("--check", str(probe))
    finally:
        probe.unlink()


def test_every_frontend_module_uses_only_bundler_syntax():
    root = web_dir()
    for path in (root / "js").rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"^import\s+(?!\{[^}]*\}\s*from\s*'[^']+';)", text, re.M), path
        assert not re.search(r"^import\s*\{[^}]*$", text, re.M), f"multi-line import in {path}"
        assert "export default" not in text and not re.search(r"^export\s*\{", text, re.M), path


def test_frontend_never_uses_inline_styles_or_scripts():
    root = web_dir()
    html = (root / "index.html").read_text(encoding="utf-8")
    assert " style=" not in html and "<style" not in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    for path in (root / "js").rglob("*.js"):
        text = path.read_text(encoding="utf-8")
        assert "setAttribute('style'" not in text and ".innerHTML" not in text, path


@needs_node
def test_js_level_bands_match_python_scoring():
    model = (web_dir() / "js" / "model.js").as_uri()
    out = run_node(
        "--input-type=module",
        "-e",
        f"import {{ BANDS }} from '{model}'; console.log(JSON.stringify(BANDS));",
    )
    js_bands = json.loads(out)
    py = [(0, "low"), *[(bound, level.label) for bound, level in scoring.BANDS]]
    assert [(b["from"], b["id"]) for b in js_bands] == py


# --- HTML report -------------------------------------------------------------


def test_html_report_is_one_self_contained_file(report):
    text = html_report.render(report)
    assert text.startswith("<!doctype html>")
    assert "window.__CHANGERISK__ =" in text and '"static": true' in text
    assert "Critical risk" in text.split("</title>")[0]
    # Nothing in the markup or the stylesheets may load anything from elsewhere...
    markup = re.sub(r"<script>.*?</script>", "", text, flags=re.S)
    assert "<link" not in markup and 'src="' not in markup and "@import" not in markup
    assert not re.search(r"https?://", markup), "markup or CSS refers to an outside address"
    # ...and the scripts have no way to fetch code. (They do contain a few URLs as text, such as the
    # link to the source and the example diff; the report view never makes a request.)
    scripts = "".join(re.findall(r"<script>(.*?)</script>", text, flags=re.S))
    assert (
        "import(" not in scripts and "XMLHttpRequest" not in scripts and "WebSocket" not in scripts
    )


def test_embedded_data_cannot_break_out_of_its_script_tag(report):
    report.findings[0].detail = "</script><script>alert(1)</script> & more \u2028"
    text = html_report.render(report)
    assert "</script><script>alert(1)" not in text
    assert "\\u003c/script\\u003e" in text


@needs_node
def test_inlined_page_scripts_parse(report, tmp_path):
    text = html_report.render(report)
    scripts = re.findall(r"<script>\n(.*?)</script>", text, re.S)
    assert len(scripts) == 2
    for i, body in enumerate(scripts):
        probe = tmp_path / f"s{i}.js"
        probe.write_text(body, encoding="utf-8")
        run_node("--check", str(probe))


def test_inline_page_needs_a_module_script(tmp_path):
    (tmp_path / "index.html").write_text(
        "<!doctype html><title>x</title><p>hi</p>", encoding="utf-8"
    )
    with pytest.raises(BundleError, match="no module script"):
        inline_page(tmp_path, "window.x = 1;", "t")


def test_html_title_is_escaped(report):
    report.head = "<b>x</b>"
    text = html_report.render(report)
    assert "<title>Critical risk (" in text and "&lt;b&gt;x&lt;/b&gt;" in text.split("</title>")[0]


# --- loading stored reports ------------------------------------------------------


def test_report_round_trips_through_json(report):
    data = json.loads(json.dumps(report.to_dict()))
    assert RiskReport.from_dict(data).to_dict() == data
