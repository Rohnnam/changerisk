"""Where the dashboard's static files live, and how they are folded into one HTML file."""

from __future__ import annotations

import os
import re
from pathlib import Path


def web_dir() -> Path:
    """The frontend directory: an override, the installed package data, or the source checkout."""
    override = os.environ.get("CHANGERISK_WEB_DIR")
    if override:
        return Path(override)
    try:
        from importlib import resources

        packaged = Path(str(resources.files("changerisk.web")))
        if (packaged / "index.html").is_file():
            return packaged
    except (ModuleNotFoundError, FileNotFoundError, TypeError):
        pass
    checkout = Path(__file__).resolve().parents[2] / "frontend"
    if (checkout / "index.html").is_file():
        return checkout
    raise FileNotFoundError("could not find the dashboard files (frontend/index.html)")


# The frontend sticks to a small module syntax so it can be bundled without a toolchain:
# single-line `import { a, b } from './x.js';` and `export function|const|let|class name`.
_IMPORT = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*'([^']+)';[ \t]*$", re.MULTILINE)
_EXPORT = re.compile(
    r"^export\s+(async\s+function|function|const|let|class)\s+([A-Za-z_$][\w$]*)", re.MULTILINE
)


class BundleError(ValueError):
    pass


def bundle_js(root: Path, entry: str = "js/main.js") -> str:
    """Concatenate the ES modules reachable from `entry` into one classic script."""
    order: list[str] = []
    sources: dict[str, str] = {}
    seen: set[str] = set()

    def resolve(importer: str, spec: str) -> str:
        base = Path(importer).parent
        target = (base / spec).as_posix()
        parts: list[str] = []
        for part in target.split("/"):
            if part == "..":
                parts.pop()
            elif part not in ("", "."):
                parts.append(part)
        return "/".join(parts)

    def visit(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        text = (root / name).read_text(encoding="utf-8")
        sources[name] = text
        for m in _IMPORT.finditer(text):
            visit(resolve(name, m.group(2)))
        order.append(name)

    visit(entry)

    def var(name: str) -> str:
        return "__m_" + re.sub(r"\W", "_", name)

    chunks = []
    for name in order:
        text = sources[name]
        lines: list[str] = []

        def take(m: re.Match[str], importer: str = name) -> str:
            names = [n.strip() for n in m.group(1).split(",") if n.strip()]
            if any(" as " in n for n in names):
                raise BundleError(f"{importer}: `as` renames are not supported by the bundler")
            return f"const {{ {', '.join(names)} }} = {var(resolve(importer, m.group(2)))};"

        body = _IMPORT.sub(take, text)
        exported = [m.group(2) for m in _EXPORT.finditer(body)]
        body = _EXPORT.sub(lambda m: m.group(0).replace("export ", "", 1), body)
        if re.search(r"^(import|export)\b", body, re.MULTILINE):
            raise BundleError(f"{name}: unsupported import/export syntax")
        ret = f"\n  return {{ {', '.join(exported)} }};" if exported else ""
        indented = "\n".join(("  " + ln) if ln else ln for ln in body.rstrip().split("\n"))
        lines.append(f"// {name}\nconst {var(name)} = (() => {{\n{indented}{ret}\n}})();")
        chunks.append("\n".join(lines))
    return "'use strict';\n" + "\n\n".join(chunks) + "\n"


_LINK = re.compile(r'<link rel="stylesheet" href="([^"]+)">')
_SCRIPT = re.compile(r'<script type="module" src="([^"]+)"></script>')


def inline_page(root: Path, data_script: str, title: str) -> str:
    """index.html with its stylesheets and script inlined and the report data placed before them."""
    html = (root / "index.html").read_text(encoding="utf-8")
    html = _LINK.sub(
        lambda m: (
            f"<style>\n{(root / m.group(1)).read_text(encoding='utf-8')}\n</style>"
            if m.group(1).endswith(".css")
            else m.group(0)
        ),
        html,
    )
    html = re.sub(r'\s*<link rel="icon"[^>]*>', "", html)
    html = re.sub(
        r"<title>.*?</title>", lambda _m: f"<title>{title}</title>", html, count=1, flags=re.S
    )
    entry = _SCRIPT.search(html)
    if not entry:
        raise BundleError("index.html has no module script to inline")
    script = bundle_js(root, entry.group(1))
    if "</script" in script.lower():
        raise BundleError("bundled script contains a closing script tag")
    replacement = f"<script>\n{data_script}\n</script>\n  <script>\n{script}</script>"
    return html[: entry.start()] + replacement + html[entry.end() :]
