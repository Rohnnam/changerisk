#!/usr/bin/env python3
"""Build a believable sample repository for trying ChangeRisk and the dashboard.

    python scripts/make_demo_repo.py [target-dir] [--force]

The repo is a small payments service ("ledgerline") with months of history, a few merged
pull requests of varying risk, and several open branches, one of them badly behaved.
The analysis history of the merged PRs is stored too, so the dashboard has a trend to show.

Credential-shaped strings are assembled at run time so this file does not trip secret scanners.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

MARKER = ".ledgerline-demo"
PRS_FILE = ".changerisk-demo-prs.json"
PEOPLE = {
    "priya": ("Priya Raman", "priya@ledgerline.example"),
    "tomas": ("Tomas Herrera", "tomas@ledgerline.example"),
    "meilin": ("Mei Lin Zhou", "meilin@ledgerline.example"),
    "daniel": ("Daniel Okafor", "daniel@ledgerline.example"),
}
STRIPE_LIVE = "sk_" + "live_" + "51Hq7LKd2eZvKYlo2C0xv9nTq8RbW3mA"
AWS_KEY = "AKIA" + "Q7XMPLK2ZD4HFWT3"


class Builder:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", PEOPLE["priya"][0])
        self.git("config", "user.email", PEOPLE["priya"][1])
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str, who: str | None = None, when: datetime | None = None) -> str:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        if who and when:
            name, email = PEOPLE[who]
            stamp = when.isoformat()
            env.update(
                GIT_AUTHOR_NAME=name, GIT_AUTHOR_EMAIL=email, GIT_COMMITTER_NAME=name,
                GIT_COMMITTER_EMAIL=email, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp,
            )  # fmt: skip
        out = subprocess.run(
            ["git", *args], cwd=self.root, env=env, capture_output=True, check=False
        )
        if out.returncode:
            raise RuntimeError(f"git {' '.join(args)}: {out.stderr.decode(errors='replace')}")
        return out.stdout.decode("utf-8", errors="replace")

    def write(self, path: str, text: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.lstrip("\n").encode("utf-8"))

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def edit(self, path: str, old: str, new: str) -> None:
        target = self.root / path
        text = target.read_text(encoding="utf-8")
        assert old in text, f"{old!r} not found in {path}"
        target.write_bytes(text.replace(old, new, 1).encode("utf-8"))

    def commit(self, message: str, who: str, when: datetime) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message, who=who, when=when)
        return self.git("rev-parse", "HEAD").strip()


def day(offset: int, hour: int = 10) -> datetime:
    return datetime(2026, 5, 4, hour, 12, tzinfo=UTC) + timedelta(days=offset)


# ---------------------------------------------------------------------------
# File contents
# ---------------------------------------------------------------------------

README = """
# ledgerline

Payments and invoicing service. Talks to the card processor, keeps the ledger,
renders customer invoices.

    pip install -r requirements.txt
    pytest
"""

REQUIREMENTS = """
django==4.2.11
requests==2.31.0
celery==5.3.6
gunicorn==21.2.0
"""

PYTEST_INI = """
[pytest]
testpaths = tests
addopts = --cov=ledgerline --cov-fail-under=85
"""

CI_WORKFLOW = """
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt pytest pytest-cov
      - run: pytest
"""

CHANGERISK_TOML = """
[gate]
fail_on = "high"

[paths]
sensitive = ["src/ledgerline/payments/**", "src/ledgerline/auth/**"]
"""

PRODUCTION_YML = """
service:
  name: ledgerline
  debug: false
payments:
  request_timeout: 10
  retry:
    max_attempts: 3
    backoff_seconds: 2
  pool_size: 20
database:
  pool_size: 10
  statement_timeout: 30s
security:
  tls_verify: true
  allowed_origins: ["https://app.ledgerline.example"]
"""

STAGING_YML = PRODUCTION_YML.replace("pool_size: 20", "pool_size: 5")

SETTINGS_PY = """
import os

DEBUG = False
REQUEST_TIMEOUT = 10
PROCESSOR_KEY = os.environ["PROCESSOR_KEY"]
SESSION_TTL = 3600
"""

CLIENT_PY = '''
"""Thin client for the card processor's HTTP API."""

import logging

import requests

from ledgerline.config import settings

log = logging.getLogger(__name__)

API_BASE = "https://api.processor.example/v2"


class ChargeError(Exception):
    pass


def charge(card_token, amount_cents):
    """Charge a tokenised card. Returns the processor's charge id."""
    resp = requests.post(
        f"{API_BASE}/charges",
        json={"source": card_token, "amount": amount_cents, "currency": "usd"},
        headers={"Authorization": f"Bearer {settings.PROCESSOR_KEY}"},
        timeout=settings.REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise ChargeError(resp.text)
    return resp.json()["id"]


def refund(charge_id, amount_cents=None):
    """Refund all or part of a charge."""
    body = {"charge": charge_id}
    if amount_cents is not None:
        body["amount"] = amount_cents
    resp = requests.post(
        f"{API_BASE}/refunds",
        json=body,
        headers={"Authorization": f"Bearer {settings.PROCESSOR_KEY}"},
    )
    if resp.status_code >= 400:
        raise ChargeError(resp.text)
    return resp.json()["id"]
'''

REFUNDS_PY = '''
"""Refund bookkeeping on our side of the ledger."""

from decimal import ROUND_HALF_EVEN, Decimal


def split_refund(total_cents, parts):
    """Divide a refund across line items without losing a cent."""
    base, extra = divmod(total_cents, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def prorate(amount_cents, used_days, period_days):
    unused = Decimal(period_days - used_days) / Decimal(period_days)
    return int((Decimal(amount_cents) * unused).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN))
'''

INVOICES_PY = '''
"""Invoice totals and line-item maths."""


class Invoice:
    def __init__(self, lines):
        self.lines = list(lines)

    def subtotal(self):
        return sum(qty * unit for qty, unit in self.lines)

    def tax(self, rate_bps):
        return self.subtotal() * rate_bps // 10_000

    def total(self, rate_bps=0):
        return self.subtotal() + self.tax(rate_bps)
'''

SESSIONS_PY = '''
"""Server-side sessions."""

import secrets
import time

from ledgerline.config import settings

_store = {}


def create(user_id):
    token = secrets.token_urlsafe(32)
    _store[token] = {"user": user_id, "expires": time.time() + settings.SESSION_TTL}
    return token


def lookup(token):
    entry = _store.get(token)
    if entry is None or entry["expires"] < time.time():
        _store.pop(token, None)
        return None
    return entry["user"]


def revoke(token):
    _store.pop(token, None)
'''

SUMMARY_PY = '''
"""Monthly summary numbers for the finance dashboard."""


def monthly_totals(rows):
    out = {}
    for month, cents in rows:
        out[month] = out.get(month, 0) + cents
    return out
'''

MIGRATIONS = {
    "0001_create_ledger.sql": "CREATE TABLE ledger (\n  id bigserial PRIMARY KEY,\n  account_id bigint NOT NULL,\n  amount_cents bigint NOT NULL,\n  created_at timestamptz NOT NULL DEFAULT now()\n);\n",
    "0002_create_invoices.sql": "CREATE TABLE invoices (\n  id bigserial PRIMARY KEY,\n  account_id bigint NOT NULL,\n  total_cents bigint NOT NULL\n);\n",
    "0003_add_ledger_memo.sql": "ALTER TABLE ledger ADD COLUMN memo text;\n",
    "0004_index_ledger_account.sql": "CREATE INDEX idx_ledger_account ON ledger (account_id);\n",
}


def test_module(name: str, cases: list[tuple[str, str]], header: str = "") -> str:
    parts = ["import pytest\n", header] if header else ["import pytest\n"]
    body = []
    for fn, assertion in cases:
        body.append(f"def test_{fn}():\n    {assertion}\n")
    return "\n".join(parts) + "\n\n" + "\n\n".join(body)


TEST_CLIENT = test_module(
    "client",
    [
        ("charge_returns_id", "assert charge('tok', 100) == 'ch_1'"),
        ("charge_sends_currency", "assert sent['currency'] == 'usd'"),
        ("charge_times_out", "assert timeout == 10"),
        ("charge_rejects_declines", "assert raises(ChargeError)"),
        ("charge_includes_auth_header", "assert header.startswith('Bearer ')"),
        ("refund_full", "assert refund('ch_1') == 're_1'"),
        ("refund_partial", "assert refund('ch_1', 50) == 're_2'"),
        ("refund_unknown_charge", "assert raises(ChargeError)"),
    ],
)
TEST_REFUNDS = test_module(
    "refunds",
    [
        ("split_even", "assert split_refund(100, 4) == [25, 25, 25, 25]"),
        ("split_uneven", "assert split_refund(10, 3) == [4, 3, 3]"),
        ("split_single", "assert split_refund(7, 1) == [7]"),
        ("split_zero", "assert split_refund(0, 3) == [0, 0, 0]"),
        ("prorate_half", "assert prorate(1000, 15, 30) == 500"),
        ("prorate_rounds_half_even", "assert prorate(5, 1, 2) == 2"),
        ("prorate_full_period", "assert prorate(1000, 30, 30) == 0"),
        ("prorate_unused", "assert prorate(1000, 0, 30) == 1000"),
        ("split_preserves_total", "assert sum(split_refund(999, 7)) == 999"),
    ],
)
TEST_INVOICES = test_module(
    "invoices",
    [
        ("subtotal", "assert Invoice([(2, 500)]).subtotal() == 1000"),
        ("tax", "assert Invoice([(1, 1000)]).tax(2000) == 200"),
        ("total_with_tax", "assert Invoice([(1, 1000)]).total(1000) == 1100"),
        ("empty_invoice", "assert Invoice([]).total() == 0"),
    ],
)
TEST_SESSIONS = test_module(
    "sessions",
    [
        ("create_and_lookup", "assert lookup(create(7)) == 7"),
        ("expired_sessions_are_gone", "assert lookup(expired) is None"),
        ("revoke", "assert lookup(revoked) is None"),
    ],
)


def seed_files(b: Builder, when: datetime) -> None:
    b.write("README.md", README)
    b.write("requirements.txt", REQUIREMENTS)
    b.write("pytest.ini", PYTEST_INI)
    b.write("changerisk.toml", CHANGERISK_TOML)
    b.write(".github/workflows/ci.yml", CI_WORKFLOW)
    b.write("config/settings.py", SETTINGS_PY)
    b.write("config/production.yml", PRODUCTION_YML)
    b.write("config/staging.yml", STAGING_YML)
    b.write("src/ledgerline/__init__.py", '"""ledgerline."""\n')
    b.write("src/ledgerline/payments/__init__.py", "")
    b.write("src/ledgerline/payments/client.py", CLIENT_PY)
    b.write("src/ledgerline/payments/refunds.py", REFUNDS_PY)
    b.write("src/ledgerline/billing/__init__.py", "")
    b.write("src/ledgerline/billing/invoices.py", INVOICES_PY)
    b.write("src/ledgerline/auth/__init__.py", "")
    b.write("src/ledgerline/auth/sessions.py", SESSIONS_PY)
    b.write("src/ledgerline/reports/__init__.py", "")
    b.write("src/ledgerline/reports/summary.py", SUMMARY_PY)
    for name, sql in list(MIGRATIONS.items())[:2]:
        b.write(f"db/migrations/{name}", sql)
    b.write("tests/test_client.py", TEST_CLIENT)
    b.write("tests/test_refunds.py", TEST_REFUNDS)
    b.write("tests/test_invoices.py", TEST_INVOICES)
    b.write("tests/test_sessions.py", TEST_SESSIONS)


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


CLIENT = "src/ledgerline/payments/client.py"

# (days after start, author, message, file, old text, new text). Each edit is small and plausible;
# the payments client collects most of the "fix" commits, which is what HIS001 looks for.
HISTORY_EDITS = [
    (
        6,
        "tomas",
        "Fix refund call missing request timeout",
        CLIENT,
        '        json=body,\n        headers={"Authorization": f"Bearer {settings.PROCESSOR_KEY}"},\n    )',
        '        json=body,\n        headers={"Authorization": f"Bearer {settings.PROCESSOR_KEY}"},\n        timeout=settings.REQUEST_TIMEOUT,\n    )',
    ),
    (
        14,
        "meilin",
        "Fix charge error dropping the processor's message",
        CLIENT,
        "raise ChargeError(resp.text)",
        'raise ChargeError(resp.text or "declined")',
    ),
    (
        23,
        "priya",
        "Fix refund failing with an empty error body",
        CLIENT,
        "raise ChargeError(resp.text)",
        'raise ChargeError(resp.text or "declined")',
    ),
    (
        37,
        "daniel",
        "Fix currency hard-coded in the charge payload",
        CLIENT,
        '"currency": "usd"}',
        '"currency": CURRENCY}',
    ),
    (
        44,
        "tomas",
        "Log charge ids at debug level",
        CLIENT,
        '    return resp.json()["id"]\n\n\ndef refund',
        '    log.debug("charged %s", resp.json()["id"])\n    return resp.json()["id"]\n\n\ndef refund',
    ),
    (
        58,
        "meilin",
        "Fix KeyError when the processor omits the charge id",
        CLIENT,
        'log.debug("charged %s", resp.json()["id"])',
        'log.debug("charged %s", resp.json().get("id"))',
    ),
    (
        66,
        "priya",
        "Fix refund rounding comment and guard",
        "src/ledgerline/payments/refunds.py",
        "return [base + (1 if i < extra else 0) for i in range(parts)]",
        "return [base + (1 if i < extra else 0) for i in range(parts)]  # earlier parts take the extra cent",
    ),
    (
        71,
        "daniel",
        "Fix bug where expired sessions were never purged",
        "src/ledgerline/auth/sessions.py",
        "        _store.pop(token, None)\n        return None",
        "        _store.pop(token, None)  # expired or unknown\n        return None",
    ),
    (
        79,
        "tomas",
        "Fix refund of a zero amount rejected by the processor",
        CLIENT,
        "    if amount_cents is not None:",
        "    if amount_cents:",
    ),
    (
        86,
        "meilin",
        "Note the API version in the client",
        CLIENT,
        'API_BASE = "https://api.processor.example/v2"',
        'API_BASE = "https://api.processor.example/v2"  # v2 since the sandbox migration',
    ),
    (
        94,
        "priya",
        "Tidy invoice docstring",
        "src/ledgerline/billing/invoices.py",
        '"""Invoice totals and line-item maths."""',
        '"""Invoice totals and line-item maths, in integer cents."""',
    ),
    (
        101,
        "daniel",
        "Fix charges failing when the card token has spaces",
        CLIENT,
        '"source": card_token,',
        '"source": card_token.strip(),',
    ),
    (
        108,
        "tomas",
        "Fix refund posted twice when the call is retried",
        CLIENT,
        '    body = {"charge": charge_id}',
        '    body = {"charge": charge_id, "idempotency_key": f"refund-{charge_id}"}',
    ),
]


def build_main_history(b: Builder) -> None:
    b.commit("Initial service skeleton", "priya", day(0))
    seed_files(b, day(0))
    b.commit("Add payments client, refunds, invoices and sessions", "priya", day(1))
    b.edit(
        CLIENT,
        'API_BASE = "https://api.processor.example/v2"',
        'API_BASE = "https://api.processor.example/v2"\nCURRENCY = "usd"',
    )
    b.commit("Pull the currency into a constant", "priya", day(2))
    for offset, who, msg, path, old, new in HISTORY_EDITS:
        b.edit(path, old, new)
        b.commit(msg, who, day(offset))
    b.git("tag", "v1.4.0", who="priya", when=day(110))


def merge_pr(b: Builder, number: int, title: str, branch: str, who: str, start: int, work) -> dict:
    """Create a branch, let `work` commit on it, then merge it with a merge commit."""
    base_sha = b.git("rev-parse", "main").strip()
    b.git("checkout", "-q", "-b", branch, "main")
    work(b, start)
    last = int(b.git("log", "-1", "--format=%ct").strip())
    b.git("checkout", "-q", "main")
    merged_at = datetime.fromtimestamp(last, UTC) + timedelta(hours=3)
    b.git(
        "merge", "--no-ff", "-q", branch, "-m", f"Merge pull request #{number} from ledgerline/{branch}\n\n{title}",
        who=who, when=merged_at,
    )  # fmt: skip
    return {
        "number": number,
        "title": title,
        "branch": branch,
        "base": base_sha,
        "merged_at": merged_at,
    }


def pr_invoice_due_date(b: Builder, start: int) -> None:
    b.edit(
        "src/ledgerline/billing/invoices.py",
        "    def __init__(self, lines):\n        self.lines = list(lines)",
        "    def __init__(self, lines, due_in_days=30):\n        self.lines = list(lines)\n        self.due_in_days = due_in_days",
    )
    b.write("db/migrations/0003_add_ledger_memo.sql", MIGRATIONS["0003_add_ledger_memo.sql"])
    b.write(
        "db/migrations/0005_add_invoice_due_days.sql",
        "ALTER TABLE invoices ADD COLUMN due_in_days int NOT NULL DEFAULT 30;\n",
    )
    b.write(
        "tests/test_invoices.py",
        TEST_INVOICES
        + "\n\ndef test_due_in_days_defaults_to_thirty():\n    assert Invoice([]).due_in_days == 30\n",
    )
    b.commit("Add due date to invoices", "priya", day(start))


def pr_refund_rounding(b: Builder, start: int) -> None:
    b.edit(
        "src/ledgerline/payments/refunds.py",
        "base, extra = divmod(total_cents, parts)",
        'if parts < 1:\n        raise ValueError("parts must be at least 1")\n    base, extra = divmod(total_cents, parts)',
    )
    b.write(
        "tests/test_refunds.py",
        TEST_REFUNDS
        + "\n\ndef test_split_rejects_zero_parts():\n    with pytest.raises(ValueError):\n        split_refund(10, 0)\n",
    )
    b.commit("Reject zero-part refund splits", "tomas", day(start))


def pr_requests_bump(b: Builder, start: int) -> None:
    b.edit("requirements.txt", "requests==2.31.0", "requests==2.32.3")
    b.commit("Bump requests to 2.32.3", "meilin", day(start))


def pr_session_expiry(b: Builder, start: int) -> None:
    b.edit("config/settings.py", "SESSION_TTL = 3600", "SESSION_TTL = 7200")
    b.edit(
        "src/ledgerline/auth/sessions.py",
        "def lookup(token):",
        'def touch(token):\n    entry = _store.get(token)\n    if entry is not None:\n        entry["expires"] = time.time() + settings.SESSION_TTL\n\n\ndef lookup(token):',
    )
    b.write(
        "tests/test_sessions.py",
        TEST_SESSIONS
        + "\n\ndef test_touch_extends_expiry():\n    token = create(1)\n    touch(token)\n    assert lookup(token) == 1\n",
    )
    b.commit("Sliding session expiry", "daniel", day(start))


def pr_docs(b: Builder, start: int) -> None:
    b.write(
        "README.md",
        README
        + "\n## Running locally\n\nSet `PROCESSOR_KEY` and run `python manage.py runserver`.\n",
    )
    b.commit("Document local setup", "priya", day(start))


def pr_celery_pool(b: Builder, start: int) -> None:
    b.edit("config/production.yml", "  pool_size: 20", "  pool_size: 40")
    b.edit("config/production.yml", "    max_attempts: 3", "    max_attempts: 5")
    b.commit("Raise payments pool for the autumn billing run", "tomas", day(start))


def pr_drop_legacy(b: Builder, start: int) -> None:
    b.write(
        "db/migrations/0006_drop_legacy_ledger.sql",
        "-- legacy_ledger was replaced by ledger in 0001\nDROP TABLE legacy_ledger;\nALTER TABLE ledger RENAME COLUMN memo TO note;\n",
    )
    b.commit("Drop legacy_ledger", "meilin", day(start))


def pr_ci_matrix(b: Builder, start: int) -> None:
    b.edit(
        ".github/workflows/ci.yml",
        "      - run: pytest",
        "      - run: pytest\n        continue-on-error: true",
    )
    b.edit(
        "tests/test_client.py",
        "def test_refund_unknown_charge():",
        "@pytest.mark.skip(reason='flaky on CI')\ndef test_refund_unknown_charge():",
    )
    b.commit("Stop the flaky refund test blocking merges", "daniel", day(start))


def pr_retry(b: Builder, start: int) -> None:
    b.edit(
        CLIENT,
        '    log.debug("charged %s", resp.json().get("id"))',
        '    if resp.status_code >= 500:\n        log.warning("processor returned %s", resp.status_code)\n    log.debug("charged %s", resp.json().get("id"))',
    )
    b.write(
        "tests/test_client.py",
        TEST_CLIENT + "\n\ndef test_server_errors_are_logged():\n    assert logged_warning\n",
    )
    b.commit("Log processor 5xx responses", "tomas", day(start))


# ---------------------------------------------------------------------------
# Open branches
# ---------------------------------------------------------------------------


def branch_faster_checkout(b: Builder) -> None:
    """The one that should not merge."""
    b.git("checkout", "-q", "-b", "feature/faster-checkout", "main")
    t0 = day(132)

    b.edit("config/production.yml", "  request_timeout: 10", "  request_timeout: 120")
    b.edit("config/production.yml", "  pool_size: 40", "  pool_size: 400")
    b.edit("config/production.yml", "  debug: false", "  debug: true")
    b.edit("config/production.yml", "  statement_timeout: 30s", "  statement_timeout: 5m")
    b.edit("config/production.yml", "  tls_verify: true", "  tls_verify: false")
    b.edit(
        "config/production.yml",
        '  allowed_origins: ["https://app.ledgerline.example"]',
        '  allowed_origins: ["*"]',
    )
    b.commit("Tune production for checkout load test", "daniel", t0)

    b.edit(
        CLIENT,
        "def charge(card_token, amount_cents):",
        'def charge(card_token, amount_cents, currency="usd", idempotency_key=None):',
    )
    b.edit(CLIENT, '"currency": CURRENCY}', '"currency": currency}')
    b.edit(
        CLIENT,
        "        timeout=settings.REQUEST_TIMEOUT,\n    )",
        "        timeout=settings.REQUEST_TIMEOUT,\n        verify=False,\n    )",
    )
    b.edit(
        CLIENT,
        "def refund(charge_id, amount_cents=None):",
        "def refund(charge_id, *, amount_cents=None, reason=None):",
    )
    b.edit(CLIENT, 'CURRENCY = "usd"', f'CURRENCY = "usd"\nFALLBACK_KEY = "{STRIPE_LIVE}"')
    quiet = (
        "\n\ndef charge_quietly(card_token, amount_cents):\n"
        '    """Never let a payment problem break checkout."""\n'
        "    try:\n        return charge(card_token, amount_cents)\n"
        "    except Exception:\n        pass\n"
    )
    path = b.root / CLIENT
    path.write_bytes(
        path.read_text(encoding="utf-8").rstrip("\n").encode("utf-8") + quiet.encode("utf-8")
    )
    b.commit(
        "Skip certificate check against the sandbox and add a fallback key",
        "daniel",
        t0 + timedelta(hours=3),
    )

    b.edit(
        "src/ledgerline/auth/sessions.py",
        "    token = secrets.token_urlsafe(32)",
        "    token = secrets.token_urlsafe(32)  # noqa: S105",
    )
    b.edit("config/settings.py", "SESSION_TTL = 7200", "SESSION_TTL = 2592000")
    b.commit("Keep users signed in for 30 days", "daniel", t0 + timedelta(hours=5))

    b.write(
        "db/migrations/0005_drop_legacy_ledger.sql",
        "DROP TABLE legacy_ledger;\nALTER TABLE ledger ADD COLUMN tenant_id bigint NOT NULL;\n",
    )
    b.write(
        "db/migrations/0003_add_ledger_memo.sql",
        "ALTER TABLE ledger ADD COLUMN memo varchar(64);\n",
    )
    b.commit("Schema for tenants", "daniel", t0 + timedelta(hours=7))

    b.edit("requirements.txt", "django==4.2.11", "django==5.0.2")
    b.edit("requirements.txt", "requests==2.32.3", "requests>=2.0")
    b.edit("requirements.txt", "gunicorn==21.2.0", "gunicorn==21.2.0\norjson==3.9.15")
    b.commit("Upgrade Django and loosen requests", "daniel", t0 + timedelta(hours=9))

    b.remove("tests/test_refunds.py")
    t = (b.root / "tests/test_client.py").read_text(encoding="utf-8")
    for gone in (
        "def test_refund_full():\n    assert refund('ch_1') == 're_1'\n\n\n",
        "def test_refund_partial():\n    assert refund('ch_1', 50) == 're_2'\n\n\n",
    ):
        assert gone in t
        t = t.replace(gone, "")
    t = t.replace(
        "def test_charge_times_out():",
        "@pytest.mark.skip(reason='takes too long')\ndef test_charge_times_out():",
    )
    (b.root / "tests/test_client.py").write_bytes(t.encode("utf-8"))
    b.edit("pytest.ini", "--cov-fail-under=85", "--cov-fail-under=60")
    b.commit("Remove slow refund tests", "daniel", t0 + timedelta(hours=11))

    b.edit(".github/workflows/ci.yml", "      - run: pytest\n", "      - run: pytest || true\n")
    b.edit(".github/workflows/ci.yml", "  pull_request:", "  pull_request_target:")
    b.edit(
        ".github/workflows/ci.yml",
        "      - uses: actions/checkout@v4",
        "      - uses: actions/checkout@v4\n        with:\n          ref: ${{ github.event.pull_request.head.sha }}",
    )
    b.commit("Make CI faster", "daniel", t0 + timedelta(hours=12))

    b.write(
        ".env.production",
        f"STRIPE_SECRET_KEY={STRIPE_LIVE}\nAWS_ACCESS_KEY_ID={AWS_KEY}\nDATABASE_URL=postgres://ledger:hunter2@db.internal/ledger\n",
    )
    b.commit("Add production env for the load test", "daniel", t0 + timedelta(hours=13))
    b.git("checkout", "-q", "main")


def branch_fix_session(b: Builder) -> None:
    b.git("checkout", "-q", "-b", "fix/session-purge", "main")
    t0 = day(131)
    b.edit(
        "src/ledgerline/auth/sessions.py",
        "def revoke(token):",
        'def purge_expired():\n    now = time.time()\n    for token in [t for t, e in _store.items() if e["expires"] < now]:\n        _store.pop(token, None)\n\n\ndef revoke(token):',
    )
    b.write(
        "tests/test_sessions.py",
        TEST_SESSIONS
        + "\n\ndef test_purge_expired_removes_old_sessions():\n    assert purge_expired() is None\n",
    )
    b.commit("Purge expired sessions on a timer", "daniel", t0)
    b.git("checkout", "-q", "main")


def branch_runbook(b: Builder) -> None:
    b.git("checkout", "-q", "-b", "docs/runbook", "main")
    b.write(
        "docs/runbook.md",
        "# Runbook\n\n## Refund stuck in pending\n\nCheck the processor dashboard, then re-run the refund job.\n",
    )
    b.commit("Add refund runbook", "priya", day(130))
    b.git("checkout", "-q", "main")


def branch_invoice_pdf(b: Builder) -> None:
    b.git("checkout", "-q", "-b", "feature/invoice-pdf", "main")
    t0 = day(128)
    body = "\n".join(f"    lines.append(f'{{label}} line {i}')" for i in range(24))
    b.write(
        "src/ledgerline/billing/pdf.py",
        f'"""Render an invoice to PDF."""\n\n\ndef render(invoice, label="Invoice"):\n    lines = []\n{body}\n    return "\\n".join(lines).encode()\n',
    )
    b.edit("requirements.txt", "gunicorn==21.2.0", "gunicorn==21.2.0\nreportlab==4.1.0")
    b.commit("Render invoices as PDF", "meilin", t0)
    b.git("checkout", "-q", "main")


# ---------------------------------------------------------------------------


def build(target: Path, force: bool) -> Path:
    if target.exists():
        if not force:
            raise SystemExit(f"{target} already exists (use --force to rebuild it)")
        if not (target / MARKER).exists():
            raise SystemExit(
                f"{target} was not created by this script (no {MARKER}); refusing to delete it"
            )
        shutil.rmtree(target, onerror=_clear_readonly)
    target.mkdir(parents=True)
    (target / MARKER).write_text("created by scripts/make_demo_repo.py\n", encoding="utf-8")
    b = Builder(target)
    build_main_history(b)

    prs = [
        merge_pr(
            b,
            41,
            "Add due date to invoices",
            "feature/invoice-due-date",
            "priya",
            112,
            pr_invoice_due_date,
        ),
        merge_pr(
            b,
            42,
            "Reject zero-part refund splits",
            "fix/refund-split-guard",
            "tomas",
            114,
            pr_refund_rounding,
        ),
        merge_pr(
            b, 43, "Bump requests to 2.32.3", "chore/bump-requests", "meilin", 116, pr_requests_bump
        ),
        merge_pr(
            b,
            44,
            "Sliding session expiry",
            "feature/sliding-sessions",
            "daniel",
            118,
            pr_session_expiry,
        ),
        merge_pr(b, 45, "Document local setup", "docs/local-setup", "priya", 119, pr_docs),
        merge_pr(b, 46, "Log processor 5xx responses", "fix/log-5xx", "tomas", 121, pr_retry),
        merge_pr(
            b,
            47,
            "Raise payments pool for the autumn billing run",
            "chore/billing-run-pool",
            "tomas",
            123,
            pr_celery_pool,
        ),
        merge_pr(
            b, 48, "Drop legacy_ledger", "chore/drop-legacy-ledger", "meilin", 125, pr_drop_legacy
        ),
        merge_pr(
            b,
            49,
            "Stop the flaky refund test blocking merges",
            "chore/unblock-ci",
            "daniel",
            127,
            pr_ci_matrix,
        ),
    ]
    branch_invoice_pdf(b)
    branch_runbook(b)
    branch_fix_session(b)
    branch_faster_checkout(b)
    b.git("checkout", "-q", "main")
    b.git("branch", "-f", "feature/faster-checkout", "feature/faster-checkout")
    b.git("config", "--local", "changerisk.demo", "true")
    prs_file = target / PRS_FILE
    prs_file.write_text(
        json.dumps([{**p, "merged_at": p["merged_at"].isoformat()} for p in prs]), encoding="utf-8"
    )
    return target


def _clear_readonly(func, path, _exc) -> None:
    os.chmod(path, 0o700)
    func(path)


def seed_dashboard(target: Path) -> None:
    from changerisk import engine
    from changerisk.store import ReportStore

    store = ReportStore(target)
    for p in _merged_prs(target):
        report = engine.analyze(target, base=p["base"], head=p["branch"], include_diffs="flagged")
        report.base = "main"
        store.save(report, created=datetime.fromisoformat(p["merged_at"]) + timedelta(minutes=4))
    report = engine.analyze(
        target, base="main", head="feature/faster-checkout", include_diffs="flagged"
    )
    store.save(report, created=day(132) + timedelta(hours=15))


def _merged_prs(target: Path) -> list[dict]:
    return json.loads((target / PRS_FILE).read_text(encoding="utf-8"))


def prune_merged(target: Path) -> None:
    """Delete the merged PR branches, the way a team would after merging."""
    b = Builder.__new__(Builder)
    b.root = target
    for p in _merged_prs(target):
        b.git("branch", "-D", p["branch"])
    (target / PRS_FILE).unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", nargs="?", default=str(ROOT / "examples" / "demo-repo"))
    parser.add_argument(
        "--force", action="store_true", help="rebuild if the target was made by this script"
    )
    parser.add_argument(
        "--no-seed", action="store_true", help="do not pre-fill the dashboard history"
    )
    args = parser.parse_args()
    target = build(Path(args.target).resolve(), args.force)
    if not args.no_seed:
        seed_dashboard(target)
    prune_merged(target)
    print(f"demo repository ready: {target}")
    print(f"  python -m changerisk serve --repo {target}")
    print(
        f"  python -m changerisk analyze --repo {target} --base main --head feature/faster-checkout"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
