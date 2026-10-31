"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_NAMES, STARTER_CONFIG, ConfigError, config_at_ref, load_config
from .engine import analyze
from .gitops import GitError, repo_root
from .reports import FORMATS, render
from .rules import load_all
from .rules.base import CATEGORIES, all_rules, get_rule, option_defaults

EXIT_OK, EXIT_GATE, EXIT_USAGE, EXIT_FAILURE = 0, 1, 2, 3
GATES = ("never", "moderate", "high", "critical")


def use_color(stream, force_off: bool = False) -> bool:
    if force_off or os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not hasattr(stream, "isatty") or not stream.isatty():
        return False
    if sys.platform == "win32":
        return any(
            os.environ.get(v) for v in ("WT_SESSION", "TERM_PROGRAM", "ANSICON", "COLORTERM")
        )
    return True


def terminal_width() -> int:
    return max(60, min(110, shutil.get_terminal_size((100, 24)).columns))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="changerisk",
        description="Score a code change and list what to test because of it.",
    )
    parser.add_argument("--version", action="version", version=f"changerisk {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="command")

    a = sub.add_parser("analyze", help="analyse a branch, the staged changes or the working tree")
    a.add_argument("--repo", default=".", help="repository path (default: current directory)")
    a.add_argument(
        "--base", help="branch or commit the change will merge into (default: main/master)"
    )
    a.add_argument("--head", help="branch or commit with the change (default: HEAD)")
    scope = a.add_mutually_exclusive_group()
    scope.add_argument("--staged", action="store_true", help="analyse what is staged for commit")
    scope.add_argument(
        "--working-tree", action="store_true", help="analyse all uncommitted changes"
    )
    a.add_argument("-f", "--format", choices=FORMATS, default="text")
    a.add_argument("-o", "--output", help="write the report to this file instead of stdout")
    a.add_argument(
        "--fail-on", choices=GATES, help="exit 1 when the level reaches this (overrides config)"
    )
    a.add_argument("--config", type=Path, help="path to a changerisk.toml")
    a.add_argument("--no-history", action="store_true", help="skip commit-history signals")
    a.add_argument("--history-days", type=int, help="how far back history signals look")
    a.add_argument("--diffs", choices=("flagged", "all", "none"), default="flagged",
                   help="which file diffs to embed in json and html reports")  # fmt: skip
    a.add_argument(
        "-v", "--verbose", action="store_true", help="show every finding and its rationale"
    )
    a.add_argument("--no-color", action="store_true")
    a.add_argument("-q", "--quiet", action="store_true", help="print nothing; use the exit code")

    s = sub.add_parser("serve", help="open the local dashboard")
    s.add_argument("--repo", default=".")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8765, help="0 picks a free port")
    s.add_argument("--no-open", action="store_true", help="do not open a browser")
    s.add_argument(
        "--hosted",
        action="store_true",
        help="run the public, stateless dashboard: no repository needed, input is a pasted diff "
        "or a public GitHub pull request (see docs/DEPLOY.md)",
    )

    r = sub.add_parser("rules", help="list the rules, or explain one")
    r.add_argument("rule_id", nargs="?", help="show details for this rule id")
    r.add_argument("--json", action="store_true", help="machine-readable output")

    i = sub.add_parser("init", help="write a starter changerisk.toml")
    i.add_argument("--repo", default=".")
    i.add_argument("--force", action="store_true", help="overwrite an existing file")

    c = sub.add_parser("ci", help="run inside GitHub Actions (comment, summary, annotations)")
    c.add_argument("--repo", default=".")
    c.add_argument("--base")
    c.add_argument("--head")
    c.add_argument("--fail-on", choices=GATES)
    c.add_argument("--config", type=Path)
    c.add_argument(
        "--use-head-config",
        action="store_true",
        help="on pull requests, read changerisk.toml from the change itself instead of the base branch",
    )
    c.add_argument("--comment", action=argparse.BooleanOptionalAction, default=True,
                   help="post or update a pull request comment")  # fmt: skip
    c.add_argument("--json", dest="json_out", help="also write the JSON report here")
    c.add_argument("--html", dest="html_out", help="also write the HTML report here")
    c.add_argument("--sarif", dest="sarif_out", help="also write a SARIF file here")
    return parser


def _emit(text: str, output: str | None, quiet: bool) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
        if not quiet:
            print(f"wrote {output}", file=sys.stderr)
    elif not quiet:
        sys.stdout.write(text)


def cmd_analyze(args: argparse.Namespace) -> int:
    mode = "staged" if args.staged else "worktree" if args.working_tree else "range"
    if mode != "range" and (args.base or args.head):
        print(
            "changerisk: --base and --head cannot be combined with --staged or --working-tree",
            file=sys.stderr,
        )
        return EXIT_USAGE
    kwargs = {}
    if args.fail_on:
        kwargs["fail_on"] = None if args.fail_on == "never" else args.fail_on
    report = analyze(
        args.repo, base=args.base, head=args.head, mode=mode, config_path=args.config,
        use_history=False if args.no_history else None, history_days=args.history_days,
        include_diffs=args.diffs if args.format in ("json", "html") else "none", **kwargs,
    )  # fmt: skip

    output = args.output
    if args.format == "html" and not output:
        output = "changerisk-report.html"
    color = use_color(sys.stdout, args.no_color) and not output
    text = render(report, args.format, color=color, width=terminal_width(), verbose=args.verbose)
    _emit(text, output, args.quiet)
    return EXIT_GATE if report.gate_failed else EXIT_OK


def cmd_rules(args: argparse.Namespace) -> int:
    load_all()
    rules = all_rules()
    if args.rule_id:
        rule = get_rule(args.rule_id.upper())
        if rule is None:
            known = ", ".join(r.info.id for r in rules)
            print(f"changerisk: no rule {args.rule_id!r}. Known rules: {known}", file=sys.stderr)
            return EXIT_USAGE
        info = rule.info
        if args.json:
            print(json.dumps(_rule_dict(info), indent=2))
            return EXIT_OK
        print(f"{info.id}  {info.name}")
        print(f"  category:  {CATEGORIES[info.category]}")
        print(f"  severity:  {info.severity.label} (default)")
        print(f"  looks for: {info.summary}")
        print(f"  why:       {info.why}")
        print("  test:")
        for t in info.tests:
            print(f"    - {t}")
        if info.options:
            print("  options:")
            for k, v in info.options.items():
                print(f"    {k} = {v!r}")
        return EXIT_OK
    if args.json:
        print(json.dumps([_rule_dict(r.info) for r in rules], indent=2))
        return EXIT_OK
    for r in rules:
        print(
            f"{r.info.id:<7} {r.info.severity.label:<9} {CATEGORIES[r.info.category]:<16} {r.info.name}"
        )
    return EXIT_OK


def _rule_dict(info) -> dict:
    return {
        "id": info.id, "name": info.name, "category": info.category,
        "severity": info.severity.label, "summary": info.summary, "why": info.why,
        "tests": list(info.tests), "options": info.options,
    }  # fmt: skip


def cmd_init(args: argparse.Namespace) -> int:
    root = repo_root(args.repo)
    target = root / CONFIG_NAMES[0]
    if target.exists() and not args.force:
        print(f"changerisk: {target} already exists (use --force to overwrite)", file=sys.stderr)
        return EXIT_USAGE
    target.write_text(STARTER_CONFIG, encoding="utf-8")
    # make sure the file we just wrote parses with the current rule set
    load_all()
    load_config(root, target, option_defaults())
    print(f"wrote {target}")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    if args.hosted:
        from .hosted import serve_hosted

        return serve_hosted(args.host, args.port)
    from .server import serve

    return serve(args.repo, args.host, args.port, open_browser=not args.no_open)


def cmd_ci(args: argparse.Namespace) -> int:
    from . import github
    from .reports import annotate, markdown

    env = os.environ
    root = repo_root(args.repo)
    base, head, pr = github.resolve_range(env, root)
    base, head = args.base or base, args.head or head
    kwargs = {}
    if args.fail_on:
        kwargs["fail_on"] = None if args.fail_on == "never" else args.fail_on
    config = None
    if pr is not None and not args.config and not args.use_head_config:
        # A pull request must not be able to loosen its own gate, so its configuration comes from the base.
        load_all()
        config = config_at_ref(root, base, option_defaults())
        print("using changerisk configuration from the base branch", file=sys.stderr)
    report = analyze(
        root, base=base, head=head, config=config, config_path=args.config,
        include_diffs="flagged", **kwargs,
    )  # fmt: skip

    sys.stdout.write(render(report, "text", color=False, width=100))
    sys.stdout.write(annotate.annotations(report))
    link = github.run_link(env)
    body = markdown.render(report, link=link)
    if github.write_summary(env, markdown.render(report, marker=False, link=link)):
        print("wrote step summary", file=sys.stderr)
    github.write_outputs(env, report)

    for path, fmt in ((args.json_out, "json"), (args.html_out, "html"), (args.sarif_out, "sarif")):
        if path:
            Path(path).write_text(render(report, fmt), encoding="utf-8")
            print(f"wrote {path}", file=sys.stderr)

    if args.comment and pr is not None:
        api = github.api_from_env(env)
        if api is None:
            print(
                "comment skipped: set GITHUB_TOKEN to post pull request comments", file=sys.stderr
            )
        else:
            print(github.upsert_comment(api, pr, body), file=sys.stderr)
    return EXIT_GATE if report.gate_failed else EXIT_OK


COMMANDS = {
    "analyze": cmd_analyze,
    "serve": cmd_serve,
    "rules": cmd_rules,
    "init": cmd_init,
    "ci": cmd_ci,
}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_USAGE
    try:
        return COMMANDS[args.command](args)
    except ConfigError as exc:
        print(f"changerisk: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except GitError as exc:
        print(f"changerisk: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:  # e.g. piped into `head`
        return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
