"""SEC001-SEC003: secrets, sensitive areas, disabled verification."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable

from ..models import ADDED, DELETED, Evidence, Finding, Severity
from ..paths import is_comment
from .base import Context, Rule, RuleInfo, evidence, join_names, plural, register, trim

SEC001 = RuleInfo(
    id="SEC001",
    name="Possible secret committed",
    category="security",
    severity=Severity.HIGH,
    summary="A value shaped like a credential, or a private key file, was added.",
    why=(
        "A committed credential is exposed to everyone with read access to the repository, now and "
        "in every clone, and stays in history after it is removed."
    ),
    tests=(
        "Treat the credential as leaked: revoke and rotate it before merging",
        "Load the value from the environment or a secret store, and scan history with a secret scanner",
    ),
)
SEC002 = RuleInfo(
    id="SEC002",
    name="Sensitive area modified",
    category="security",
    severity=Severity.MEDIUM,
    summary="Code for authentication, sessions, permissions, crypto or payments changed.",
    why=(
        "Bugs in these areas are security incidents or lost money, not just defects, and they "
        "rarely show up in happy-path tests."
    ),
    tests=(
        "Test the negative paths: expired and forged tokens, missing permissions, replayed requests",
        "Ask a second reviewer who knows this area to read the changes in {paths}",
    ),
    options={"high_lines": 80},
)
SEC003 = RuleInfo(
    id="SEC003",
    name="Certificate or signature checks disabled",
    category="security",
    severity=Severity.HIGH,
    summary="TLS verification, host key checking or similar was switched off in code.",
    why=(
        "Turning verification off lets anyone on the network path impersonate the server. It is "
        "usually added to get past a local certificate error and then ships."
    ),
    tests=(
        "Connect with an untrusted certificate and confirm the call fails",
        "Fix the certificate chain instead of disabling the check",
    ),
)

_PROVIDERS = (
    ("AWS access key id", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), 1),
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----"), 1),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b"), 1),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b"), 1),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b"), 1),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), 0),
    ("JSON web token", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), 0),
)  # fmt: skip
_GENERIC = re.compile(
    # No leading prefix: a lazy `[\w.-]*?` here made the search quadratic on long runs of word
    # characters (a minified bundle, or hostile input). `search` already finds PASSWORD in DB_PASSWORD.
    r"""(?ix)(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key|
    client[_-]?secret|auth[_-]?token)\b["']?\s*[:=]\s*["']([^"'\s]{8,})["']"""
)
_PLACEHOLDER = (
    "example", "changeme", "change_me", "your", "xxxx", "dummy", "sample", "placeholder",
    "redacted", "todo", "fake", "<", ">", "${", "{{", "%(", "environ", "getenv", "secret", "password",
)  # fmt: skip
# Text keys are caught by their BEGIN header; these are stores that hold secrets without one.
_KEY_FILES = re.compile(r"(?i)(?:^|/)(?:.+\.(?:p12|pfx|jks|keystore)|\.htpasswd)$")

_SENSITIVE_WORDS = {
    "auth": "authentication", "authn": "authentication", "authz": "authorization",
    "login": "authentication", "logout": "authentication", "signin": "authentication",
    "signup": "authentication", "session": "sessions", "sessions": "sessions",
    "password": "passwords", "passwords": "passwords", "credential": "credentials",
    "credentials": "credentials", "permission": "permissions", "permissions": "permissions",
    "rbac": "permissions", "acl": "permissions", "oauth": "authentication", "oidc": "authentication",
    "saml": "authentication", "sso": "authentication", "jwt": "tokens", "token": "tokens",
    "tokens": "tokens", "crypto": "cryptography", "encrypt": "cryptography",
    "encryption": "cryptography", "signing": "cryptography", "payment": "payments",
    "payments": "payments", "billing": "billing", "checkout": "payments", "invoice": "billing",
    "invoices": "billing", "wallet": "payments", "pii": "personal data", "kms": "cryptography",
    "vault": "secrets", "iam": "permissions",
}  # fmt: skip

_VERIFY_OFF = re.compile(
    r"\bverify\s*=\s*False\b|\brejectUnauthorized\s*:\s*false\b|\bInsecureSkipVerify\s*:\s*true\b|"
    r"\bCURLOPT_SSL_VERIFY(?:PEER|HOST)\s*,\s*(?:false|0)\b|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0|"
    r"\b_create_unverified_context\b|\bcheck_hostname\s*=\s*False\b|StrictHostKeyChecking[= ]+no\b|"
    r"\bverify_ssl\s*[:=]\s*(?:false|False)\b|\bcurl\b[^\n|]*\s(?:-k|--insecure)\b|--no-check-certificate"
)


def mask(value: str) -> str:
    keep = min(4, max(0, len(value) // 4))
    return value[:keep] + "*" * min(12, len(value) - keep)


def entropy(value: str) -> float:
    counts = {c: value.count(c) for c in set(value)}
    n = len(value)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def looks_real(value: str) -> bool:
    low = value.lower()
    if any(p in low for p in _PLACEHOLDER):
        return False
    if len(set(value)) <= 3:
        return False
    if not (re.search(r"\d", value) and re.search(r"[A-Za-z]", value)):
        return False
    return entropy(value) >= 3.0


def find_secrets(text: str) -> list[tuple[str, str, int]]:
    """Return (kind, secret, bump) for each credential-shaped value in a line."""
    found = []
    for kind, pattern, bump in _PROVIDERS:
        for m in pattern.finditer(text):
            if "EXAMPLE" in m.group(0).upper():
                continue
            found.append((kind, m.group(0), bump))
    for m in _GENERIC.finditer(text):
        value = m.group(2)
        if not any(value in secret for _, secret, _ in found) and looks_real(value):
            found.append((f"hard-coded {m.group(1).lower()}", value, 0))
    return found


def masked_line(text: str, secrets: list[tuple[str, str, int]]) -> str:
    for _, secret, _ in secrets:
        text = text.replace(secret, mask(secret))
    return text


@register
class SecretCommitted(Rule):
    info = SEC001

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.status == ADDED and _KEY_FILES.search(fc.path):
                yield self._key_file(ctx, fc.path)
                continue
            if fc.binary:
                continue
            kinds: list[str] = []
            ev: list[Evidence] = []
            top = 0
            for ln in ctx.added(fc, self.info.id):
                secrets = find_secrets(ln.text)
                if not secrets:
                    continue
                kinds += [k for k, _, _ in secrets]
                top = max(top, *(b for _, _, b in secrets))
                ev.append(evidence(fc.path, ln.new_no, masked_line(ln.text, secrets)))
            if not ev:
                continue
            unique = list(dict.fromkeys(kinds))
            lowered = -1 if ctx.paths.is_test(fc.path) and top == 0 else 0
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} contains what looks like {join_names(unique)} "
                f"({plural(len(ev), 'line')}). The value is masked here.",
                paths=[fc.path],
                evidence=ev,
                bump=top + lowered,
            )

    def _key_file(self, ctx: Context, path: str) -> Finding:
        return ctx.finding(
            self.info,
            detail=f"{path} looks like a credential store and was added.",
            paths=[path],
            evidence=[evidence(path, None, "key material file added")],
        )


@register
class SensitiveArea(Rule):
    info = SEC002

    def check(self, ctx: Context) -> Iterable[Finding]:
        high_lines = int(ctx.options(self.info)["high_lines"])
        areas: dict[str, list] = defaultdict(list)
        for fc in ctx.files:
            if fc.binary or not fc.changed_lines:
                continue
            if (
                ctx.paths.is_test(fc.path)
                or ctx.paths.is_doc(fc.path)
                or ctx.paths.is_generated(fc.path)
            ):
                continue
            area = self._area_of(ctx, fc.path)
            if area:
                areas[area].append(fc)
        for area, files in areas.items():
            lines = sum(f.changed_lines for f in files)
            files.sort(key=lambda f: f.changed_lines, reverse=True)
            names = join_names([f.path for f in files], limit=2)
            yield ctx.finding(
                self.info,
                title=f"Sensitive area modified: {area}",
                detail=f"{plural(len(files), 'file')} touching {area} changed "
                f"({plural(lines, 'line')}): {names}.",
                paths=[f.path for f in files],
                evidence=[
                    evidence(f.path, None, f"{f.changed_lines} lines changed") for f in files
                ],
                bump=1 if lines >= high_lines else 0,
            )

    @staticmethod
    def _area_of(ctx: Context, path: str) -> str | None:
        if ctx.paths.is_sensitive_path(path):
            return "paths marked sensitive"
        spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", path)
        for token in re.split(r"[^a-zA-Z0-9]+", spaced.lower()):
            if token in _SENSITIVE_WORDS:
                return _SENSITIVE_WORDS[token]
        return None


@register
class VerificationDisabled(Rule):
    info = SEC003

    def check(self, ctx: Context) -> Iterable[Finding]:
        for fc in ctx.files:
            if fc.binary or fc.status == DELETED or ctx.paths.is_doc(fc.path):
                continue
            lang = ctx.paths.language(fc.path)
            hits = [
                ln
                for ln in ctx.added(fc, self.info.id)
                if _VERIFY_OFF.search(ln.text) and not is_comment(ln.text, lang)
            ]
            if not hits:
                continue
            yield ctx.finding(
                self.info,
                detail=f"{fc.path} turns off certificate or host verification "
                f"({plural(len(hits), 'place')}).",
                paths=[fc.path],
                evidence=[evidence(fc.path, ln.new_no, trim(ln.text)) for ln in hits],
                bump=-1 if ctx.paths.is_test(fc.path) else 0,
            )
