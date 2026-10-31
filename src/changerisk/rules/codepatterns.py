"""COD001-COD003: risky calls, swallowed errors, silenced checks."""

from __future__ import annotations

import re
from collections.abc import Iterable

from ..models import DELETED, Finding, Severity
from ..paths import is_comment
from .base import Context, Rule, RuleInfo, evidence, plural, register, suppressed

COD001 = RuleInfo(
    id="COD001",
    name="Risky call added",
    category="code",
    severity=Severity.MEDIUM,
    summary="eval/exec, unsafe deserialisation, shell=True, string-built SQL, raw HTML injection.",
    why=(
        "These calls turn data into behaviour. When the data comes from a user, a file or a "
        "network peer, they become injection or remote-code-execution holes."
    ),
    tests=(
        "Trace where each argument comes from and test with hostile input (quotes, newlines, ../, <script>)",
        "Replace with the safe alternative (parameterised queries, argument lists, json/safe_load, textContent)",
    ),
)
COD002 = RuleInfo(
    id="COD002",
    name="Error handling reduced",
    category="code",
    severity=Severity.MEDIUM,
    summary="Errors are swallowed by empty handlers, or try/catch blocks were removed.",
    why=(
        "An error that is caught and ignored turns a loud failure into silent wrong results, "
        "which are far harder to find in production."
    ),
    tests=(
        "Make the dependency fail on purpose and check the user sees an error and a log line appears",
        "Check callers still handle the failure the removed code used to deal with",
    ),
)
COD003 = RuleInfo(
    id="COD003",
    name="Checks suppressed",
    category="code",
    severity=Severity.LOW,
    summary="noqa, type: ignore, eslint-disable, nosec and similar markers were added.",
    why=(
        "Each suppression hides a warning someone decided to see. One is routine; several in one "
        "change usually mean the warnings were in the way."
    ),
    tests=(
        "Remove each suppression and read the warning it was hiding",
        "Confirm the reason is written next to every suppression that stays",
    ),
    options={"many": 5},
)

# (pattern, label, languages or None for any, raises severity)
_RISKY = (
    (re.compile(r"(?<![\w.])eval\s*\("), "eval()", {"python", "javascript", "typescript", "php", "ruby"}, True),
    (re.compile(r"(?<![\w.])exec\s*\("), "exec()", {"python"}, True),
    (re.compile(r"\bpickle\.loads?\("), "pickle deserialisation", {"python"}, True),
    (re.compile(r"\byaml\.load\((?![^)]*Loader)"), "yaml.load without a safe loader", {"python"}, True),
    (re.compile(r"\bsubprocess\.\w+\([^)]*shell\s*=\s*True"), "shell=True", {"python"}, True),
    (re.compile(r"\bos\.(?:system|popen)\("), "os.system / os.popen", {"python"}, True),
    (re.compile(r"\bhashlib\.(?:md5|sha1)\("), "weak hash (md5/sha1)", {"python"}, False),
    (re.compile(r"\btempfile\.mktemp\("), "tempfile.mktemp", {"python"}, False),
    (re.compile(r"\bnew\s+Function\("), "new Function()", {"javascript", "typescript"}, True),
    (re.compile(r"\.innerHTML\s*="), "innerHTML assignment", {"javascript", "typescript"}, False),
    (re.compile(r"dangerouslySetInnerHTML"), "dangerouslySetInnerHTML", {"javascript", "typescript"}, False),
    (re.compile(r"\bdocument\.write\("), "document.write", {"javascript", "typescript"}, False),
    (re.compile(r"\bchild_process\b.*\bexec\("), "child_process.exec", {"javascript", "typescript"}, True),
    (re.compile(r"""\.(?:execute|query|raw)\(\s*f["']"""), "SQL built with an f-string", {"python"}, True),
    (re.compile(r"""(?i)\.(?:execute|query)\(\s*["'][^"']*\b(?:select|insert|update|delete)\b[^"']*["']\s*(?:%|\+|\.format)"""), "SQL built by string formatting", None, True),
    (re.compile(r"\bchmod\s+(?:-R\s+)?0?777\b"), "chmod 777", {"shell", None}, False),
    (re.compile(r"\bcurl\b[^|\n]*\|\s*(?:sudo\s+)?(?:ba)?sh\b"), "curl | sh", {"shell", None}, True),
)  # fmt: skip

_SWALLOW_PY = re.compile(
    r"^\s*except(?:\s+(?:Exception|BaseException)(?:\s+as\s+\w+)?)?\s*:\s*(?:#.*)?$"
)
_NOOP = re.compile(r"^\s*(?:pass|\.\.\.|continue)\s*(?:#.*)?$")
_EMPTY_CATCH = re.compile(r"\bcatch\s*(?:\([^)]*\))?\s*\{\s*\}")
_HANDLER = re.compile(r"^\s*(?:\}\s*)?(?:except\b|catch\b|rescue\b)")

_SUPPRESS = re.compile(
    r"#\s*noqa\b|#\s*type:\s*ignore|#\s*pylint:\s*disable|#\s*nosec\b|#\s*pragma:\s*no\s*cover|"
    r"eslint-disable|@ts-ignore|@ts-nocheck|//\s*nolint|@SuppressWarnings|#\[allow\(|"
    r"#\s*rubocop:disable|//\s*NOSONAR"
)
_HARD_SUPPRESS = re.compile(r"#\s*nosec\b|@ts-nocheck|eslint-disable(?!-next-line|-line)")


def _code_files(ctx: Context):
    for fc in ctx.files:
        if fc.binary or fc.status == DELETED:
            continue
        if (
            ctx.paths.is_test(fc.path)
            or ctx.paths.is_doc(fc.path)
            or ctx.paths.is_generated(fc.path)
        ):
            continue
        yield fc, ctx.paths.language(fc.path)


@register
class RiskyCall(Rule):
    info = COD001

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc, lang in _code_files(ctx):
            if lang is None and not fc.path.endswith((".sh", ".bash", ".yml", ".yaml")):
                continue
            hits: list[tuple[int, str, str, bool]] = []
            for ln in ctx.added(fc, self.info.id):
                if is_comment(ln.text, lang):
                    continue
                for pattern, label, langs, severe in _RISKY:
                    if langs is not None and lang not in langs:
                        continue
                    if pattern.search(ln.text):
                        hits.append((ln.new_no or 0, ln.text, label, severe))
                        break
            if not hits:
                continue
            labels = list(dict.fromkeys(label for _, _, label, _ in hits))
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} adds {', '.join(labels[:3])}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, no, text) for no, text, _, _ in hits],
                bump=1 if any(s for *_, s in hits) else 0,
            )


@register
class ErrorHandling(Rule):
    info = COD002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc, lang in _code_files(ctx):
            swallowed: list[tuple[int, str]] = []
            for hunk in fc.hunks:
                body = [ln for ln in hunk.lines if ln.kind != "-"]
                for i, ln in enumerate(body):
                    if ln.kind != "+" or suppressed(ln.text, self.info.id):
                        continue
                    if lang == "python" and _SWALLOW_PY.match(ln.text):
                        nxt = body[i + 1] if i + 1 < len(body) else None
                        if nxt is not None and _NOOP.match(nxt.text):
                            swallowed.append(
                                (ln.new_no or 0, f"{ln.text.strip()}  {nxt.text.strip()}")
                            )
                    elif lang in (
                        "javascript",
                        "typescript",
                        "java",
                        "csharp",
                        "kotlin",
                    ) and _EMPTY_CATCH.search(ln.text):
                        swallowed.append((ln.new_no or 0, ln.text.strip()))
            removed = [ln for ln in fc.removed_lines() if _HANDLER.match(ln.text)]
            added = [ln for ln in fc.added_lines() if _HANDLER.match(ln.text)]
            net = len(removed) - len(added)
            parts = []
            ev = [evidence(fc.path, no, text) for no, text in swallowed]
            if swallowed:
                parts.append(f"{plural(len(swallowed), 'error handler')} that ignore the error")
            if net >= 2:
                parts.append(f"{net} error handlers removed")
                ev += [evidence(fc.path, ln.old_no, ln.text, "old") for ln in removed]
            if not parts:
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path}: {' and '.join(parts)}.",
                paths=[fc.path],
                evidence=ev,
            )


@register
class ChecksSuppressed(Rule):
    info = COD003

    def check(self, ctx: Context) -> Iterable[Finding]:
        many = int(ctx.options(self.info)["many"])
        for fc, _lang in _code_files(ctx):
            hits = [ln for ln in ctx.added(fc, self.info.id) if _SUPPRESS.search(ln.text)]
            if not hits:
                continue
            hard = any(_HARD_SUPPRESS.search(ln.text) for ln in hits)
            yield ctx.finding(
                self.info,
                detail=f"{plural(len(hits), 'lint or type check')} suppressed in {fc.path}.",
                paths=[fc.path],
                evidence=[evidence(fc.path, ln.new_no, ln.text) for ln in hits],
                bump=1 if hard or len(hits) >= many else 0,
            )
