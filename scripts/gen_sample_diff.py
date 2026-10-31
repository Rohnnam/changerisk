#!/usr/bin/env python3
"""Write frontend/js/sample-diff.js: the examples the hosted dashboard offers to try.

The diff comes from a real `git diff` between two small trees, so its hunks are exact. The one
credential-shaped value is a placeholder here and is filled in by the page at runtime from pieces,
so no string in the repository looks like a live key to a secret scanner.

    python scripts/gen_sample_diff.py
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "frontend" / "js" / "sample-diff.js"

BASE = {
    "config/production.yml": (
        "service:\n  name: ledgerline\n  debug: false\npayments:\n  request_timeout: 10\n"
        "  pool_size: 20\nsecurity:\n  tls_verify: true\n"
    ),
    "src/ledgerline/payments/client.py": (
        'import requests\n\nAPI_BASE = "https://api.processor.example/v2"\n\n\n'
        "def charge(card_token, amount_cents):\n"
        '    resp = requests.post(\n        f"{API_BASE}/charges",\n'
        '        json={"source": card_token, "amount": amount_cents},\n        timeout=10,\n    )\n'
        '    return resp.json()["id"]\n'
    ),
    "tests/test_refunds.py": (
        "def test_full_refund():\n    assert refund(10) == 10\n\n\n"
        "def test_partial_refund():\n    assert refund(5) == 5\n\n\n"
        "def test_refund_after_chargeback():\n    assert refund(1) == 0\n"
    ),
    "requirements.txt": "django==4.2.11\nrequests==2.31.0\ncelery==5.3.6\n",
    ".github/workflows/ci.yml": (
        "name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n      - run: pytest\n"
    ),
}

CRITICAL = {
    "config/production.yml": (
        "service:\n  name: ledgerline\n  debug: true\npayments:\n  request_timeout: 120\n"
        "  pool_size: 200\nsecurity:\n  tls_verify: false\n"
    ),
    "src/ledgerline/payments/client.py": (
        'import requests\n\nAPI_BASE = "https://api.processor.example/v2"\n'
        'FALLBACK_KEY = "__STRIPE_KEY__"\n\n\n'
        'def charge(card_token, amount_cents, currency="usd"):\n'
        '    resp = requests.post(\n        f"{API_BASE}/charges",\n'
        '        json={"source": card_token, "amount": amount_cents},\n        timeout=10,\n'
        "        verify=False,\n    )\n"
        '    return resp.json()["id"]\n'
    ),
    "requirements.txt": "django==5.0.2\nrequests>=2.0\ncelery==5.3.6\n",
    ".github/workflows/ci.yml": (
        "name: ci\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n"
        "    steps:\n      - uses: actions/checkout@v4\n      - run: pytest || true\n"
    ),
    "db/migrations/0005_drop_legacy_ledger.sql": "DROP TABLE legacy_ledger;\n",
}


RECEIPTS = (
    'def format_receipt(charge_id, amount_cents, currency="usd"):\n'
    "    dollars, cents = divmod(amount_cents, 100)\n"
    '    return f"{charge_id}: {dollars}.{cents:02d} {currency.upper()}"\n'
)


def tidy() -> dict[str, str]:
    """A small addition that arrives with its own test and a note in the docs."""
    head = dict(BASE)
    head["src/ledgerline/payments/receipts.py"] = RECEIPTS
    head["tests/test_receipts.py"] = (
        "from ledgerline.payments.receipts import format_receipt\n\n\n"
        "def test_amounts_are_padded_to_two_places():\n"
        '    assert format_receipt("ch_1", 1205) == "ch_1: 12.05 USD"\n'
    )
    head["docs/receipts.md"] = (
        "# Receipts\n\nA receipt line is the charge id, the amount and the currency.\n"
    )
    return head


def review() -> dict[str, str]:
    """Each edit is ordinary; together they ask for a second pair of eyes."""
    head = dict(BASE)
    head["config/production.yml"] = BASE["config/production.yml"].replace(
        "request_timeout: 10", "request_timeout: 15"
    )
    head["requirements.txt"] = "django==4.2.11\nrequests>=2.0\ncelery==5.3.6\n"
    head["tests/test_refunds.py"] = BASE["tests/test_refunds.py"].replace(
        "def test_partial_refund():\n    assert refund(5) == 5\n\n\n", ""
    )
    return head


# What the dashboard offers on its first screen. `expect` is checked against the engine by a test.
SCENARIOS = [
    {
        "id": "tidy",
        "label": "Small change",
        "title": "A small change with its test",
        "summary": "A helper, a test for it and a docs page. It sits in the payments code, so that is noted.",
        "expect": "low",
        "head": tidy,
    },
    {
        "id": "review",
        "label": "Edits that add up",
        "title": "Ordinary edits, taken together",
        "summary": "A longer timeout, a loosened version pin and a deleted test.",
        "expect": "moderate",
        "head": review,
    },
    {
        "id": "critical",
        "label": "Should not merge",
        "title": "A change that should not merge",
        "summary": "Debug on, TLS off, a key in the code, a table dropped and a test removed.",
        "expect": "critical",
        "head": lambda: CRITICAL,
    },
]


def git(root: Path, *args: str) -> str:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="Sample", GIT_AUTHOR_EMAIL="sample@example.com",
        GIT_COMMITTER_NAME="Sample", GIT_COMMITTER_EMAIL="sample@example.com",
    )  # fmt: skip
    out = subprocess.run(["git", *args], cwd=root, env=env, capture_output=True, check=True)
    return out.stdout.decode("utf-8")


def write_tree(root: Path, tree: dict[str, str], removed: set[str]) -> None:
    for name in removed:
        (root / name).unlink(missing_ok=True)
    for name, text in tree.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(text.encode("utf-8"))


def build_diff(head: dict[str, str]) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        git(root, "init", "-q", "-b", "main")
        git(root, "config", "core.autocrlf", "false")
        write_tree(root, BASE, set())
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "base")
        write_tree(root, head, set(BASE) - set(head))
        git(root, "add", "-A")
        git(root, "commit", "-q", "-m", "head")
        return git(root, "diff", "--no-color", "-M", "HEAD~1", "HEAD")


def build_all() -> dict[str, str]:
    return {item["id"]: build_diff(item["head"]()) for item in SCENARIOS}


def render(diffs: dict[str, str]) -> str:
    lines = {name: diff.rstrip("\n").split("\n") for name, diff in diffs.items()}
    cards = ",\n".join(
        "  {\n"
        f"    id: {json.dumps(item['id'])},\n"
        f"    label: {json.dumps(item['label'])},\n"
        f"    title: {json.dumps(item['title'])},\n"
        f"    summary: {json.dumps(item['summary'])},\n"
        f"    expect: {json.dumps(item['expect'])},\n"
        f"    diff: fill(DIFFS[{json.dumps(item['id'])}]),\n"
        "  }"
        for item in SCENARIOS
    )
    return (
        "// Generated by scripts/gen_sample_diff.py. Edit the script, not this file.\n"
        "// The diffs are a made-up payments service: one ordinary change, one that adds up, and one with\n"
        "// the changes ChangeRisk is meant to catch. The key is assembled here so no string in the\n"
        "// repository looks like one.\n\n"
        f"const DIFFS = {json.dumps(lines, indent=2, ensure_ascii=False)};\n\n"
        "const FAKE_KEY = 'sk_' + 'live_' + '51Hq7LKd2eZvKYlo2C0xv9nTq8RbW3mA';\n\n"
        "const fill = (lines) => lines.join('\\n').replace('__STRIPE_KEY__', FAKE_KEY) + '\\n';\n\n"
        f"export const EXAMPLES = [\n{cards},\n];\n\n"
        "export const SAMPLE_DIFF = EXAMPLES[EXAMPLES.length - 1].diff;\n"
    )


def main() -> int:
    TARGET.write_text(render(build_all()), encoding="utf-8", newline="\n")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
