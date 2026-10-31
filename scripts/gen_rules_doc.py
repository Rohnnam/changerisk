#!/usr/bin/env python3
"""Write docs/RULES.md from the rule registry, so the reference cannot drift from the code.

python scripts/gen_rules_doc.py          # rewrite the file
python scripts/gen_rules_doc.py --check  # exit 1 if it is out of date
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from changerisk.rules import load_all  # noqa: E402
from changerisk.rules.base import CATEGORIES, all_rules  # noqa: E402

TARGET = ROOT / "docs" / "RULES.md"

INTRO = """\
# Rules

Generated from the rule registry by `scripts/gen_rules_doc.py`. Do not edit by hand; change the
rule's metadata in `src/changerisk/rules/` and regenerate.

Every rule has a stable id. To turn one off, or change how it counts, use `changerisk.toml`:

```toml
[rules]
disable = ["COD003"]

[rules.SIZ001]
medium_lines = 600     # the rule's own options (listed below)
severity = "high"      # replaces the default severity, which findings can still step up from
weight = 0.5           # scales the points; 0 silences it
```

To suppress a rule for one line, put `changerisk: ignore RULE_ID` in a comment on that line.
Rules that look at added lines honour it; rules about files as a whole do not.

Severity is the starting point. Many rules step one level up or down depending on what they
find (a production path, a 10x jump, a test file), so a finding can differ from the default.
"""


def render() -> str:
    load_all()
    rules = all_rules()
    out = [INTRO]
    out.append("## Summary\n")
    out.append("| Id | Name | Area | Default severity |")
    out.append("|---|---|---|---|")
    for r in rules:
        i = r.info
        out.append(
            f"| [{i.id}](#{i.id.lower()}) | {i.name} | {CATEGORIES[i.category]} | {i.severity.label} |"
        )
    out.append("")
    for category, label in CATEGORIES.items():
        members = [r for r in rules if r.info.category == category]
        if not members:
            continue
        out.append(f"## {label}\n")
        for r in members:
            i = r.info
            out.append(f"### {i.id}")
            out.append(f"**{i.name}**. Default severity: {i.severity.label}.\n")
            out.append(f"*Looks for:* {i.summary}\n")
            out.append(f"*Why it matters:* {i.why}\n")
            out.append("*What to test:*\n")
            out.extend(f"- {t}" for t in i.tests)
            if i.options:
                out.append("\n*Options:*\n")
                out.extend(f"- `{k}` (default `{v}`)" for k, v in i.options.items())
            out.append("")
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != text:
            print("docs/RULES.md is out of date; run scripts/gen_rules_doc.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
