#!/usr/bin/env python3
"""Write the two files of the Hugging Face Space: README.md and index.html.

The Space is static. Its index.html is the dashboard's page with every asset address pointing at
this repository at one commit, through jsDelivr, and a block of settings telling the page where to
find Pyodide and the bundled Python. Pinning a commit means the Space never changes underneath
its readers; to update it, build again with a newer commit and upload the two files.

    python scripts/build_space.py --ref <commit sha>
    python scripts/build_space.py --base http://127.0.0.1:8123/      # for trying it locally

The commit must contain frontend/py/changerisk-py.json (python scripts/build_browser_bundle.py).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from changerisk import __version__  # noqa: E402

REPO = "Rohnnam/changerisk"
JSDELIVR = "https://cdn.jsdelivr.net"
PYODIDE = f"{JSDELIVR}/pyodide/v0.27.7/full/"
SHA = re.compile(r"[0-9a-f]{40}")
ASSET = re.compile(r'(?P<attr>href|src)="(?P<path>(?:css|js|img)/[^"]+)"')

# The page runs Python compiled to WebAssembly, so it needs wasm-unsafe-eval; everything else is
# kept to the two places its files come from and the two GitHub hosts it may read.
POLICY = (
    "default-src 'none'; "
    "script-src {assets} {pyodide} 'wasm-unsafe-eval'; "
    "style-src {assets}; img-src {assets} data:; font-src {assets}; "
    "connect-src {assets} {pyodide} https://api.github.com https://raw.githubusercontent.com; "
    "worker-src blob:; base-uri 'none'; form-action 'none'"
)

FRONT_MATTER = """---
title: ChangeRisk
emoji: 🔎
colorFrom: gray
colorTo: red
sdk: static
pinned: false
short_description: Score a code change and see what to test
---

# ChangeRisk

Click one of the built-in examples, paste a git diff or give a public GitHub pull request, and
ChangeRisk scores how risky the change is and lists what to test because of it: edited configuration, removed tests, loosened
dependencies, committed secrets, destructive migrations, weakened pipelines.

The analysis runs inside your browser (Python compiled to WebAssembly). A pasted diff is never sent
anywhere. A pull request is fetched from GitHub by your browser, directly.

Source, the command line and the GitHub Action: https://github.com/{repo}
"""


def assets_base(ref: str | None, base: str | None) -> str:
    if base:
        return base if base.endswith("/") else base + "/"
    if not ref or not SHA.fullmatch(ref):
        raise SystemExit("--ref must be a full 40-character commit sha, so the Space stays pinned")
    return f"{JSDELIVR}/gh/{REPO}@{ref}/frontend/"


def build_index(assets: str) -> str:
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    html = ASSET.sub(lambda m: f'{m["attr"]}="{assets}{m["path"]}"', html)
    settings = {
        "browser": {
            "version": __version__,
            "worker": f"{assets}js/browser-worker.js",
            "bundle": f"{assets}py/changerisk-py.json",
            "pyodide": PYODIDE,
        }
    }
    head_extra = (
        '  <meta http-equiv="Content-Security-Policy" content="'
        + POLICY.format(assets=assets.rstrip("/") + "/", pyodide=PYODIDE)
        + '">\n  <meta name="referrer" content="no-referrer">\n'
    )
    config = (
        '  <script type="application/json" id="changerisk-config">'
        + json.dumps(settings, separators=(",", ":"))
        + "</script>\n"
    )
    html = html.replace("  <title>", head_extra + "  <title>", 1)
    html = html.replace('  <script type="module"', config + '  <script type="module"', 1)
    return html


def build_readme() -> str:
    return FRONT_MATTER.format(repo=REPO)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--ref", help="full commit sha of this repository to serve the files from")
    parser.add_argument("--base", help="serve the files from this URL instead (local testing)")
    parser.add_argument("--out", default="dist/space", help="where to write the two files")
    args = parser.parse_args()

    assets = assets_base(args.ref, args.base)
    out = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "index.html").write_text(build_index(assets), encoding="utf-8", newline="\n")
    (out / "README.md").write_text(build_readme(), encoding="utf-8", newline="\n")
    print(f"wrote {out / 'index.html'} and {out / 'README.md'}\nassets: {assets}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
