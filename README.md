# ChangeRisk

ChangeRisk reads the diff of a change (a branch, a pull request, what you have staged) and tells
you how risky it is and why. It looks for the things a reviewer skims past: a production timeout
raised tenfold, a test file deleted, a lockfile that did not move with its manifest, a migration
that drops a table, a CI step set to `continue-on-error`, a key pasted into a config file.

The result is a risk report. The score is only the headline. Each report also gives the reasons
behind it with the actual lines quoted, and a checklist of what to test because of them.

```
ChangeRisk  demo-repo  main...feature/faster-checkout  (12 files, +35 -67, 8 commits)

  RISK  CRITICAL   score 100/100   gate FAILED (fails at high)

  Do not merge until the critical findings are dealt with and the test plan is done. The main
  reasons: safety setting flipped, workflow permissions or triggers widened and possible secret
  committed, plus 21 more.
  Next: Hold the merge. Resolve the critical findings, then run this check again.

  Why this needs extra testing  (ranked by points)

   1. [CRIT] +30.0 Safety setting flipped
          config/production.yml: debug was switched on; tls_verify was switched off;
          allowed_origins now accepts everything ('*').
          config/production.yml:3  + debug: true
          config/production.yml:14  + tls_verify: false

   3. [CRIT] +30.0 Possible secret committed
          .env.production contains what looks like Stripe live key and AWS access key id (2
          lines). The value is masked here.
          .env.production:1  + STRIPE_SECRET_KEY=<hidden>
   ...
```

It needs Python 3.11 or newer and git. It has no runtime dependencies, makes no network calls while
analysing, and does not run your tests. It says what to test; running them is up to you.

## Install

ChangeRisk is not on PyPI yet. Install it from a checkout:

```bash
pip install .
changerisk --version
```

## Use it

Analyse the current branch against `main` (or `master`, whichever exists):

```bash
changerisk analyze
changerisk analyze --base origin/main --head my-branch
changerisk analyze --staged          # what you are about to commit
changerisk analyze --working-tree    # everything uncommitted, new files included
```

Pick a format with `-f`: `text` (default), `markdown`, `json`, `html`, `github` (workflow
annotations) or `sarif`. `-o FILE` writes to a file. `-v` shows every finding and why it matters.

| Exit code | Meaning |
|---|---|
| 0 | Analysed, and the level is below the gate |
| 1 | The level reached the gate (`--fail-on`, default `high`) |
| 2 | Bad usage or an invalid `changerisk.toml` |
| 3 | git failed, or the repository could not be read |

Other commands:

```bash
changerisk rules                 # list the rules; `changerisk rules CFG003` explains one
changerisk init                  # write a starter changerisk.toml
changerisk serve                 # open the dashboard
```

### The dashboard

`changerisk serve` starts a local server on `127.0.0.1:8765` and opens the dashboard. Pick two refs,
press Analyse, and read the report: the verdict and score on a ruler with the build gate marked on
it, the ranked reasons, a test plan you can tick off, the changed files with the flagged lines
marked in the diff, and the trend across your recent analyses. Reports are kept in `.changerisk/`
inside the repository (the folder ignores itself). Any report can be exported as one self-contained
HTML file, Markdown, JSON or SARIF.

To try it without a real repository:

```bash
python scripts/make_demo_repo.py          # builds examples/demo-repo
changerisk serve --repo examples/demo-repo
```

### In GitHub Actions

```yaml
name: changerisk
on: pull_request

permissions:
  contents: read
  pull-requests: write      # lets it post and update the comment

jobs:
  risk:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0    # needed for the merge base and for history signals
      - uses: Rohnnam/changerisk@v1
        with:
          fail-on: high
```

It posts one comment on the pull request and updates it on every push, writes the same report to the
job summary, adds annotations on the flagged lines, and fails the step when the level reaches
`fail-on`. On pull requests from forks the token is read-only; the comment is skipped and the rest
still works. Inputs and outputs are listed in [action.yml](action.yml).

On pull requests the configuration is read from the base branch, not from the change, so a pull
request cannot switch off its own gate by editing `changerisk.toml`. (A change that edits the file is
still reported as a configuration change.) Pass `--use-head-config` to `changerisk ci` to opt out.

### Hosted mode

`changerisk serve --hosted` runs the same dashboard as a public service with no repository behind it.
The change comes from a pasted diff or a public GitHub pull request, nothing is stored on the server,
and reports stay in the visitor's browser. It is built for deployment (there is a `Dockerfile`, and a
ready-made Docker Space in `deploy/hf-space-docker/`) and carries the protections a public service
needs: rate limits, size caps, a fixed list of hosts it may contact, and tested resistance to
pathological input. See [docs/DEPLOY.md](docs/DEPLOY.md). Use the local dashboard for private
repositories: it reads the repository directly and also uses commit history.

### In the browser, with no server

The same dashboard also runs with nothing behind it: the Python engine is compiled to WebAssembly
(Pyodide) and runs in a worker inside the page, so a pasted diff never leaves the visitor's machine
and the host only serves static files. That is how the public Space is deployed, and it is why the
Space costs nothing to keep up. HTML export and a shared GitHub allowance need a server; everything
else is the same. `scripts/build_space.py` builds it, and [docs/DEPLOY.md](docs/DEPLOY.md) explains
the differences.

## Configuration

Everything is optional. `changerisk init` writes a commented starter file. A `changerisk.toml` in the
repository root, or a `[tool.changerisk]` table in `pyproject.toml`, is picked up automatically.

```toml
[gate]
fail_on = "high"                  # never | moderate | high | critical

[paths]
ignore = ["docs/**"]              # left out of the analysis entirely
sensitive = ["src/billing/**"]    # extra paths that count as security-sensitive

[rules]
disable = ["COD003"]

[rules.SIZ001]
medium_lines = 600
```

Mistakes are reported with a suggestion (`unknown rule 'CFG01' (did you mean 'CFG001'?)`). To suppress a
line-level rule in one place, add `changerisk: ignore CFG002` in a comment on that line. The
[rule reference](docs/RULES.md) lists every rule with its options.

## How the score works

Each finding is worth points by severity: low 3, medium 8, high 16, critical 30. A rule that fires
again counts for half, then a quarter, so ten similar hits do not bury everything else. The points
add up to a total, and `score = 100 * (1 - exp(-total / 40))`, which grows quickly at first and
never passes 100. Levels: below 25 low, below 50 moderate, below 75 high, otherwise critical. A
critical finding makes the level at least high, and a high finding at least moderate, however the
points add up.

The points shown beside each finding add up to the total, so a report can be checked by hand.

## What it looks at

33 rules in ten areas: configuration, tests, dependencies, security, pipelines, database
migrations, size and spread, history, public interfaces, and code patterns. The two that started the
project are deliberately the most thorough: edited configuration (which key changed, from what to
what, by how much) and removed tests (deleted files, removed cases, skips, dropped assertions, lowered
coverage gates). See [docs/RULES.md](docs/RULES.md).

Secrets are never printed. Credential-shaped values are masked in findings, and every diff line in a
report is redacted again on the way out, so a report is safe to share.

## Limits

* The rules are pattern-based. They read the diff, not a syntax tree, so they miss things and they
  guess wrong sometimes. Each rule is conservative, can be disabled, and quotes its evidence so a
  wrong guess is easy to spot.
* Test, assertion and public-interface detection understands Python, JavaScript and TypeScript, Go,
  and (for tests only) Ruby, Java, Kotlin, C# and Rust. Other languages still get the rules that do
  not depend on syntax.
* History signals need a full clone. In a shallow clone they are skipped and the report says so.
* The score is a triage aid, not a verdict on whether the code is correct.

## Development

```bash
python -m venv .venv
.venv/Scripts/activate            # or: source .venv/bin/activate
pip install -e ".[dev]"

pytest                            # backend tests, against real git repositories
ruff check . && ruff format --check .
cd frontend && node --test        # dashboard unit tests (Node 20+)
python scripts/gen_rules_doc.py   # after changing a rule's metadata
```

```
src/changerisk/        the package: git layer, rules, scoring, reports, CLI, server
frontend/              the dashboard: HTML, CSS and ES modules, no build step
tests/                 pytest suite
scripts/               demo repository generator, rule reference generator
docs/                  architecture, API, design notes, rule reference, build plan
action.yml             the GitHub Action
.github/workflows/     this project's CI, and ChangeRisk checking its own pull requests
```

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) explains how the pieces fit and how to add a rule.
[docs/API.md](docs/API.md) documents the dashboard's HTTP API and the report format.
[docs/DESIGN.md](docs/DESIGN.md) records the dashboard's design decisions.
[docs/DEPLOY.md](docs/DEPLOY.md) covers hosted mode: running it, its settings, and its threat model.
