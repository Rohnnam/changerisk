"""CFG001-CFG004: configuration changes."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from ..models import ADDED, DELETED, FileChange, Finding, Severity
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register, suppressed

CFG001 = RuleInfo(
    id="CFG001",
    name="Configuration changed",
    category="config",
    severity=Severity.LOW,
    summary="A configuration file was edited, added or removed. Production files rank one step higher.",
    why=(
        "Configuration is not covered by unit tests. A wrong value passes CI and only fails when "
        "a real environment loads it, usually under production traffic."
    ),
    tests=(
        "Start the service with {path} and run its smoke tests",
        "Diff the effective settings from {path} against the previous release in staging",
    ),
)
CFG002 = RuleInfo(
    id="CFG002",
    name="Safety setting flipped",
    category="config",
    severity=Severity.HIGH,
    summary="Debug switched on, or TLS, auth, CSRF or validation switched off, or access opened to '*'.",
    why=(
        "These switches exist to protect users and data. Flipping one is easy to do for a quick "
        "local test and easy to forget about in a merge."
    ),
    tests=(
        "Confirm the new value in {path} is intended for every environment that reads it",
        "Exercise the protected path (login, TLS handshake, CSRF check) and confirm it still rejects bad input",
    ),
)
CFG003 = RuleInfo(
    id="CFG003",
    name="Operational limit changed sharply",
    category="config",
    severity=Severity.MEDIUM,
    summary="A timeout, pool size, retry count, rate or similar limit moved by a large factor.",
    why=(
        "Limits tune how the system behaves under stress. A tenfold timeout hides slow "
        "dependencies, a pool that is too large exhausts the database, and a value of zero often "
        "means unlimited."
    ),
    tests=(
        "Load test with the new values in {path} and watch connection counts, queue depth and latency",
        "Fail a dependency on purpose (slow it down, drop it) and check how the service reacts",
    ),
    options={"factor": 2.0},
)
CFG004 = RuleInfo(
    id="CFG004",
    name="Environment file tracked",
    category="config",
    severity=Severity.HIGH,
    summary="A real .env file (not an example or template) is part of the change.",
    why=(
        "Environment files usually hold credentials. Once one is committed, its values live in "
        "history even after the file is deleted."
    ),
    tests=(
        "Rotate any credential that appeared in the file",
        "Move the values to a secret store and commit only a .env.example",
    ),
)

_KV = (
    re.compile(r'^\s*"([^"]+)"\s*:\s*(.*?),?\s*$'),  # json
    re.compile(r"^\s*(?:ENV|ARG)\s+([A-Za-z_]\w*)[= ]\s*(.*?)\s*$"),  # dockerfile
    re.compile(r"^\s*(FROM|USER|EXPOSE|WORKDIR|ENTRYPOINT|CMD)\s+(.+?)\s*$"),
    re.compile(
        r"^\s*(?:export\s+)?([A-Za-z_][\w.\-/]*)\s*[:=]\s*(.*?)\s*$"
    ),  # yaml, env, ini, toml
)
_COMMENT = re.compile(r"^\s*(#|;|//|/\*|\*)")
_TRAILING_COMMENT = re.compile(r"\s+(#|//)\s.*$")
_TRUE = {"true", "yes", "on", "1", "enabled", "enable"}
_FALSE = {"false", "no", "off", "0", "disabled", "disable", "none", "null"}
_DEBUG_WORDS = {"debug", "devmode", "verbose"}
_SAFETY_WORDS = {
    "ssl", "tls", "https", "verify", "verification", "secure", "csrf", "xsrf", "auth",
    "authentication", "authorization", "signature", "mfa", "encrypt", "encryption", "validate",
    "validation", "sandbox", "strict", "checksum", "audit", "ratelimit",
}  # fmt: skip
_OPEN_WORDS = {"origin", "origins", "hosts", "allowed"}
_LIMIT_WORDS = {
    "timeout", "timeouts", "ttl", "retries", "retry", "limit", "limits", "max", "pool",
    "workers", "concurrency", "threads", "interval", "backoff", "batch", "memory", "cpu",
    "replicas", "rate", "capacity", "connections", "delay", "expiry", "expires", "lifetime",
    "quota", "burst", "size",
}  # fmt: skip
SECRET_WORDS = {"password", "passwd", "secret", "token", "key", "credential", "credentials"}
_PROD = {"prod", "production", "prd", "live"}
_LOW_TIER = {"dev", "development", "local", "example", "sample"}

_TIME = {
    "ms": 0.001,
    "s": 1,
    "sec": 1,
    "secs": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "h": 3600,
    "d": 86400,
}
_SIZE = {
    "b": 1, "k": 1e3, "kb": 1e3, "ki": 1024, "kib": 1024, "mb": 1e6, "mi": 1024**2,
    "mib": 1024**2, "g": 1e9, "gb": 1e9, "gi": 1024**3, "gib": 1024**3,
}  # fmt: skip


FLIP_TESTS = {
    "debug": (
        "Confirm debug stays off in every environment that serves real traffic, including {path}",
        "Trigger an error on a deployed instance and check no stack trace or settings page is shown",
    ),
    "off": (
        "Exercise the protected path (TLS handshake, login, CSRF check) and confirm it still rejects bad input",
        "Confirm the switch is still on in every environment that reads {path}",
    ),
    "open": (
        "Send a cross-origin or foreign-host request from an origin that is not listed and confirm it is rejected",
    ),
}


@dataclass
class KeyChange:
    key: str
    old: str | None
    new: str | None
    old_line: int | None
    new_line: int | None
    old_text: str
    new_text: str

    @property
    def kind(self) -> str:
        if self.old is None:
            return "added"
        if self.new is None:
            return "removed"
        return "changed"


def key_tokens(key: str) -> set[str]:
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    parts = [p for p in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if p]
    # Also offer run-together words such as "devmode" or "ratelimit".
    return set(parts) | {"".join(parts[i : i + 2]) for i in range(len(parts) - 1)}


def tier(path: str) -> str:
    tokens = {t for t in re.split(r"[^a-z0-9]+", path.lower()) if t}
    if tokens & _PROD:
        return "prod"
    if tokens & _LOW_TIER:
        return "low"
    return "normal"


def tier_bump(path: str) -> int:
    return {"prod": 1, "low": -1}.get(tier(path), 0)


def parse_kv(line: str, path: str) -> tuple[str, str] | None:
    if not line.strip() or _COMMENT.match(line):
        return None
    for pattern in _KV:
        m = pattern.match(line)
        if m:
            key, value = m.group(1), _TRAILING_COMMENT.sub("", m.group(2)).strip()
            value = value.strip().strip(",").strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if value == "" or value in ("{", "[", "|", ">"):
                return None  # a parent key, not a setting
            return key, value
    return None


def key_changes(fc: FileChange) -> list[KeyChange]:
    """Pair removed and added `key: value` lines inside each hunk."""
    out: list[KeyChange] = []
    for hunk in fc.hunks:
        removed: dict[str, tuple[str, int | None, str]] = {}
        added: dict[str, tuple[str, int | None, str]] = {}
        for ln in hunk.lines:
            if ln.kind == " ":
                continue
            kv = parse_kv(ln.text, fc.path)
            if kv is None:
                continue
            target = removed if ln.kind == "-" else added
            target[kv[0]] = (kv[1], ln.old_no if ln.kind == "-" else ln.new_no, ln.text)
        for key in list(dict.fromkeys([*removed, *added])):
            old, new = removed.get(key), added.get(key)
            if old and new and old[0] == new[0]:
                continue
            out.append(
                KeyChange(
                    key=key,
                    old=old[0] if old else None,
                    new=new[0] if new else None,
                    old_line=old[1] if old else None,
                    new_line=new[1] if new else None,
                    old_text=old[2] if old else "",
                    new_text=new[2] if new else "",
                )
            )
    return out


def is_env_file(path: str) -> bool:
    return PurePosixPath(path).name.lower().startswith(".env")


def shown(path: str, key: str, value: str | None) -> str:
    """The value as it may appear in a report. Secrets and env files are never echoed."""
    if value is None:
        return "(unset)"
    if is_env_file(path) or key_tokens(key) & SECRET_WORDS:
        return "<hidden>"
    return value if len(value) <= 40 else value[:37] + "..."


def evidence_for(path: str, ch: KeyChange):
    """Evidence line for a key change; secret values are replaced with a marker."""
    if ch.new is not None:
        text, line, side = ch.new_text, ch.new_line, "new"
    else:
        text, line, side = ch.old_text, ch.old_line, "old"
    value = ch.new if ch.new is not None else ch.old
    if shown(path, ch.key, value) == "<hidden>":
        text = f"{ch.key} = <hidden>"
    return evidence(path, line, text, side)


def truthy(value: str | None) -> bool | None:
    if value is None:
        return None
    v = value.strip().lower()
    if v in _TRUE:
        return True
    if v in _FALSE:
        return False
    return None


def parse_quantity(value: str) -> tuple[float, str] | None:
    """Parse '30', '30s', '512Mi' into (number in base units, unit class)."""
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)\s*([a-zA-Z]*)\s*", value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2).lower()
    if unit == "":
        return number, ""
    if unit in _TIME:
        return number * _TIME[unit], "time"
    if unit in _SIZE:
        return number * _SIZE[unit], "size"
    return None


def _config_files(ctx: Context) -> Iterable[FileChange]:
    for fc in ctx.files:
        if fc.binary or not ctx.paths.is_config(fc.path):
            continue
        yield fc


def _substantive(fc: FileChange) -> bool:
    """False when only comments or blank lines changed."""
    for ln in (*fc.added_lines(), *fc.removed_lines()):
        if ln.text.strip() and not _COMMENT.match(ln.text):
            return True
    return False


@register
class ConfigChanged(Rule):
    info = CFG001

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in _config_files(ctx):
            if is_env_file(fc.path):
                continue  # CFG004 covers these
            if fc.status in (ADDED, DELETED) and not fc.hunks:
                continue
            if not _substantive(fc):
                continue
            changes = key_changes(fc)
            if fc.status == ADDED:
                detail = f"{fc.path} was added with {plural(fc.additions, 'line')}."
            elif fc.status == DELETED:
                detail = f"{fc.path} was deleted."
            elif changes:
                bits = [self._describe(fc.path, c) for c in changes[:3]]
                more = len(changes) - len(bits)
                tail = f"; and {more} more" if more > 0 else ""
                detail = f"{fc.path}: {'; '.join(bits)}{tail}."
            else:
                detail = f"{fc.path} changed ({fc.additions} added, {fc.deletions} removed)."
            if changes:
                ev = [evidence_for(fc.path, c) for c in changes]
            else:
                ev = [
                    evidence(fc.path, ln.new_no, ln.text)
                    for ln in fc.added_lines()
                    if ln.text.strip()
                ]
            yield ctx.finding(
                self.info, detail=detail, paths=[fc.path], evidence=ev, bump=tier_bump(fc.path)
            )

    @staticmethod
    def _describe(path: str, c: KeyChange) -> str:
        if c.kind == "added":
            return f"{c.key} added ({shown(path, c.key, c.new)})"
        if c.kind == "removed":
            return f"{c.key} removed"
        return f"{c.key} changed from {shown(path, c.key, c.old)} to {shown(path, c.key, c.new)}"


@register
class SafetyFlipped(Rule):
    info = CFG002

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in _config_files(ctx):
            if is_env_file(fc.path):
                continue
            hits: list[tuple[KeyChange, str]] = []
            for c in key_changes(fc):
                if suppressed(c.new_text, self.info.id):
                    continue
                why = self._classify(c)
                if why:
                    hits.append((c, why))
            if not hits:
                continue
            kinds = {self._kind(why) for _, why in hits}
            tests = [t for k in ("debug", "off", "open") if k in kinds for t in FLIP_TESTS[k]]
            bits = [f"{c.key} {why}" for c, why in hits[:3]]
            more = len(hits) - len(bits)
            detail = f"{fc.path}: {'; '.join(bits)}" + (f"; and {more} more." if more > 0 else ".")
            yield ctx.finding(
                self.info,
                detail=detail,
                paths=[fc.path],
                evidence=[evidence_for(fc.path, c) for c, _ in hits],
                bump=tier_bump(fc.path),
                tests=tests,
            )

    @staticmethod
    def _kind(why: str) -> str:
        if "on" in why.split():
            return "debug"
        return "open" if "'*'" in why else "off"

    @staticmethod
    def _classify(c: KeyChange) -> str | None:
        tokens = key_tokens(c.key)
        old, new = truthy(c.old), truthy(c.new)
        if tokens & _DEBUG_WORDS and new is True and old is not True:
            return "was switched on"
        if tokens & _SAFETY_WORDS and new is False and old is not False:
            return "was switched off" if old is not None else "was added as off"
        if tokens & _OPEN_WORDS and c.new is not None:
            opened = re.sub(r"[\s\[\]'\"]", "", c.new) == "*"
            was_open = c.old is not None and re.sub(r"[\s\[\]'\"]", "", c.old) == "*"
            if opened and not was_open:
                return "now accepts everything ('*')"
        return None


@register
class LimitChanged(Rule):
    info = CFG003

    def check(self, ctx: Context) -> Iterable[Finding]:
        factor = float(ctx.options(self.info)["factor"])
        for fc in _config_files(ctx):
            if is_env_file(fc.path):
                continue
            hits: list[tuple[KeyChange, str, int]] = []
            for c in key_changes(fc):
                if c.old is None or c.new is None or not key_tokens(c.key) & _LIMIT_WORDS:
                    continue
                verdict = self._judge(c.old, c.new, factor)
                if verdict:
                    hits.append((c, *verdict))
            if not hits:
                continue
            # Only a sharp jump (10x, or down to zero) raises the level, and not in dev-tier files.
            bump = 1 if any(b for _, _, b in hits) and tier(fc.path) != "low" else 0
            bits = [
                f"{c.key} {phrase} (from {shown(fc.path, c.key, c.old)} to {shown(fc.path, c.key, c.new)})"
                for c, phrase, _ in hits[:3]
            ]
            more = len(hits) - len(bits)
            detail = f"{fc.path}: {'; '.join(bits)}" + (f"; and {more} more." if more > 0 else ".")
            yield ctx.finding(
                self.info,
                detail=detail,
                paths=[fc.path],
                evidence=[evidence_for(fc.path, c) for c, _, _ in hits],
                bump=bump,
            )

    @staticmethod
    def _judge(old: str, new: str, factor: float) -> tuple[str, int] | None:
        a, b = parse_quantity(old), parse_quantity(new)
        if a is None or b is None or a[1] != b[1]:
            return None
        before, after = a[0], b[0]
        if before == after:
            return None
        if after == 0 and before > 0:
            return "was set to zero, which often means unlimited", 1
        if before <= 0:
            return None
        ratio = after / before
        if ratio >= factor:
            return f"rose {_times(ratio)}", 1 if ratio >= 10 else 0
        if ratio <= 1 / factor:
            return f"fell to {_times(1 / ratio, inverse=True)}", 1 if ratio <= 0.1 else 0
        return None


def _times(ratio: float, inverse: bool = False) -> str:
    text = f"{ratio:.0f}" if ratio >= 10 or ratio == int(ratio) else f"{ratio:.1f}"
    return f"1/{text}" if inverse else f"{text}x"


@register
class EnvFileTracked(Rule):
    info = CFG004

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if not is_env_file(fc.path) or not ctx.paths.is_config(fc.path):
                continue
            if fc.status == DELETED:
                continue
            keys = []
            ev = []
            for ln in fc.added_lines():
                kv = parse_kv(ln.text, fc.path)
                if kv:
                    keys.append(kv[0])
                    ev.append(evidence(fc.path, ln.new_no, f"{kv[0]} = <hidden>"))
            named = f" It defines {join_names(keys)}." if keys else ""
            verb = "was added to" if fc.status == ADDED else "was changed in"
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} {verb} the repository.{named}",
                paths=[fc.path],
                evidence=ev,
            )
