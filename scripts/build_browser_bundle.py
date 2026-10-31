#!/usr/bin/env python3
"""Write frontend/py/changerisk-py.json: the Python package as one file, for the browser build.

The page loads this next to Pyodide and writes the files into its in-memory file system. Only the
modules the browser needs go in; the server, CLI and dashboard-file code stay out, which keeps it
small and means nothing in it expects a socket, a subprocess or a disk.

    python scripts/build_browser_bundle.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from changerisk import __version__  # noqa: E402

SRC = ROOT / "src"
TARGET = ROOT / "frontend" / "py" / "changerisk-py.json"
# Needs a server, a terminal, a repository on disk, or the dashboard's files.
EXCLUDED = {
    "changerisk/__main__.py",
    "changerisk/cli.py",
    "changerisk/server.py",
    "changerisk/hosted.py",
    "changerisk/github.py",
    "changerisk/store.py",
    "changerisk/webassets.py",
    "changerisk/reports/html.py",
}


def collect() -> dict[str, str]:
    files = {}
    for path in sorted((SRC / "changerisk").rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel not in EXCLUDED:
            files[rel] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return files


def render() -> str:
    bundle = {"version": __version__, "files": collect()}
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"


def main() -> int:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    text = render()
    TARGET.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)} ({len(text) // 1024} KB, {len(collect())} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
