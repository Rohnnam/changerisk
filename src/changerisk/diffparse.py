"""Parser for `git diff` unified output."""

from __future__ import annotations

import re

from .models import (
    ADDED,
    COPIED,
    DELETED,
    MODIFIED,
    RENAMED,
    TYPECHANGE,
    FileChange,
    Hunk,
    Line,
)

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_OCTAL = re.compile(r"\\([0-7]{3})")
_SIMPLE_ESCAPES = {"t": "\t", "n": "\n", "r": "\r", '"': '"', "\\": "\\", "a": "\a", "b": "\b"}


def unquote(token: str) -> str:
    """Undo git's C-style path quoting (quotes, escapes, octal bytes)."""
    if len(token) < 2 or not (token.startswith('"') and token.endswith('"')):
        return token
    raw = token[1:-1]
    out = bytearray()
    i = 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            m = _OCTAL.match(raw, i)
            if m:
                out.append(int(m.group(1), 8))
                i += 4
                continue
            out += _SIMPLE_ESCAPES.get(raw[i + 1], raw[i + 1]).encode("utf-8")
            i += 2
            continue
        out += c.encode("utf-8")
        i += 1
    return out.decode("utf-8", errors="replace")


def _strip_prefix(path: str) -> str:
    path = unquote(path)
    if path[:2] in ("a/", "b/"):
        return path[2:]
    return path


def _paths_from_git_header(rest: str) -> tuple[str, str] | None:
    """Pull (old, new) out of `a/X b/Y`. Only reliable when both names are equal or quoted."""
    rest = rest.strip()
    if rest.startswith('"'):
        end = _closing_quote(rest)
        if end is None:
            return None
        first = rest[: end + 1]
        second = rest[end + 1 :].strip()
        return _strip_prefix(first), _strip_prefix(second)
    n = len(rest)
    if n % 2 == 1:
        mid = n // 2
        left, right = rest[:mid], rest[mid + 1 :]
        if rest[mid] == " " and left[2:] == right[2:]:
            return left[2:], right[2:]
    # Names differ (rename) or contain a quote: split at " b/" and hope.
    idx = rest.find(" b/")
    if idx > 0:
        return rest[2:idx], rest[idx + 3 :]
    return None


def _closing_quote(s: str) -> int | None:
    i = 1
    while i < len(s):
        if s[i] == "\\":
            i += 2
            continue
        if s[i] == '"':
            return i
        i += 1
    return None


def parse_diff(text: str) -> list[FileChange]:
    files: list[FileChange] = []
    current: FileChange | None = None
    hunk: Hunk | None = None
    old_no = new_no = 0
    old_left = new_left = 0
    header_done = False  # true once the first hunk of the current file has started

    def finish() -> None:
        nonlocal current, hunk
        if current is not None:
            current.count_lines()
            files.append(current)
        current = None
        hunk = None

    for raw in text.split("\n"):
        # A hunk line never starts a new file section, so check hunk state first.
        if hunk is not None and (old_left > 0 or new_left > 0):
            line = raw.rstrip("\r")
            tag = line[:1]
            if tag == "+":
                hunk.lines.append(Line("+", None, new_no, line[1:]))
                new_no += 1
                new_left -= 1
                continue
            if tag == "-":
                hunk.lines.append(Line("-", old_no, None, line[1:]))
                old_no += 1
                old_left -= 1
                continue
            if tag == " " or line == "":
                hunk.lines.append(Line(" ", old_no, new_no, line[1:]))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
                continue
            if tag == "\\":
                continue

        if raw.startswith("\\"):  # "\ No newline at end of file" after the last counted line
            continue

        if raw.startswith("diff --git "):
            finish()
            paths = _paths_from_git_header(raw[len("diff --git ") :])
            current = FileChange(path=paths[1] if paths else "?")
            header_done = False
            continue

        if current is None:
            continue

        m = _HUNK.match(raw)
        if m:
            header_done = True
            hunk = Hunk(
                old_start=int(m.group(1)),
                old_len=int(m.group(2) if m.group(2) is not None else 1),
                new_start=int(m.group(3)),
                new_len=int(m.group(4) if m.group(4) is not None else 1),
                header=m.group(5).strip(),
            )
            old_no, new_no = hunk.old_start, hunk.new_start
            old_left, new_left = hunk.old_len, hunk.new_len
            current.hunks.append(hunk)
            continue

        if header_done:
            continue

        _apply_header_line(current, raw)

    finish()
    return files


def _apply_header_line(fc: FileChange, raw: str) -> None:
    if raw.startswith("new file mode"):
        fc.status = ADDED
    elif raw.startswith("deleted file mode"):
        fc.status = DELETED
    elif raw.startswith("old mode "):
        fc.mode_change = (raw[len("old mode ") :].strip(), "")
    elif raw.startswith("new mode "):
        old = fc.mode_change[0] if fc.mode_change else ""
        fc.mode_change = (old, raw[len("new mode ") :].strip())
        if old.startswith("120") != raw[len("new mode ") :].strip().startswith("120"):
            fc.status = TYPECHANGE
    elif raw.startswith("similarity index "):
        fc.similarity = int(raw.split()[-1].rstrip("%"))
    elif raw.startswith("rename from "):
        fc.status = RENAMED
        fc.old_path = unquote(raw[len("rename from ") :])
    elif raw.startswith("rename to "):
        fc.status = RENAMED
        fc.path = unquote(raw[len("rename to ") :])
    elif raw.startswith("copy from "):
        fc.status = COPIED
        fc.old_path = unquote(raw[len("copy from ") :])
    elif raw.startswith("copy to "):
        fc.status = COPIED
        fc.path = unquote(raw[len("copy to ") :])
    elif raw.startswith(("Binary files ", "GIT binary patch")):
        fc.binary = True
        _binary_paths(fc, raw)
    elif raw.startswith("--- "):
        name = raw[4:].split("\t")[0]
        if name != "/dev/null":
            candidate = _strip_prefix(name)
            if fc.status in (MODIFIED, DELETED):
                fc.path = candidate
            if fc.old_path is None and fc.status == RENAMED:
                fc.old_path = candidate
    elif raw.startswith("+++ "):
        name = raw[4:].split("\t")[0]
        if name != "/dev/null":
            fc.path = _strip_prefix(name)


_BINARY = re.compile(r"^Binary files (.+) and (.+) differ$")


def _binary_paths(fc: FileChange, raw: str) -> None:
    m = _BINARY.match(raw)
    if not m:
        return
    old, new = m.group(1), m.group(2)
    if old == "/dev/null":
        fc.status = ADDED
    if new == "/dev/null":
        fc.status = DELETED
        fc.path = _strip_prefix(old)
    elif new.startswith(("b/", '"b/')):
        fc.path = _strip_prefix(new)
