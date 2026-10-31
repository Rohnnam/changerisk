# ChangeRisk: execution plan

Working notes for building ChangeRisk end to end. Each segment lists what gets built, how it is checked, and when it counts as finished. Status boxes are ticked as the work lands.

## 1. What we are building

A tool that reads the diff of a proposed change (a pull request, a branch, staged files) and says how risky it is and why. It looks for the things reviewers miss: a production config value changed by 10x, tests deleted, a lockfile that did not move with its manifest, a migration that drops a table, a CI step quietly set to `continue-on-error`.

The output is a **risk report**. The report is the product. A score alone is not useful, so every score comes with the reasons behind it, the evidence (file and line), and a concrete list of what to test because of it.

Stack from the brief: Git, GitHub Actions, Python, pytest.

### Scope

In:
- Diff analysis over a git range, the index, or the working tree
- About 30 rules across config, tests, dependencies, security, CI, database, size, history, interfaces and code patterns
- An explainable score (0-100), a level (low, moderate, high, critical), and a gate that can fail a build
- Output as terminal text, Markdown (PR comment), JSON, GitHub annotations, SARIF, and a standalone HTML report
- A GitHub Action that comments on pull requests and fails the check at a chosen level
- A local dashboard to run analyses, read reports, and see the trend across past analyses

Out (deliberately):
- Machine learning or any network call during analysis. The tool is deterministic and works offline.
- Running the project's tests. ChangeRisk says what to test; it does not run it.
- Hosting or accounts. The dashboard is local.

## 2. Architecture

```
git repo ──► gitops ──► diff parser ──► ChangeSet
                                          │
              config (changerisk.toml) ───┤
              history signals (git log) ──┤
                                          ▼
                                    rule engine  (one module per category)
                                          │ findings
                                          ▼
                                  scoring + explain
                      (points, level, verdict, test plan)
                                          │ RiskReport
              ┌──────────┬────────────┬───┴────────┬──────────────┐
              ▼          ▼            ▼            ▼              ▼
            text     markdown       json      annotations/     html (standalone)
           (CLI)   (PR comment)  (API, store)     SARIF         dashboard (served)
```

Layout on disk:

```
src/changerisk/        backend package (CLI, engine, rules, reports, server)
frontend/              dashboard (HTML, CSS, ES modules; no build step)
tests/                 pytest suite (real git repos in temp dirs)
.github/workflows/     CI for this project + dogfooding workflow
action.yml             the reusable GitHub Action
scripts/               demo repo generator, rule docs generator
docs/                  plan, architecture, rules, API, design notes
```

## 3. Segments

### Segment A: foundations
- [x] Project scaffold: `pyproject.toml`, `.gitignore`, `.editorconfig`, virtualenv, dev tools (pytest, pytest-cov, ruff)
- [x] Domain model: `ChangeSet`, `FileChange`, `Hunk`, `Finding`, `RiskReport`
- [x] Path classification: test / source / config / lockfile / generated / docs

Done when: models import cleanly, classification has table-driven tests.

### Segment B: git layer
- [x] Safe git runner (argument lists only, timeouts, no shell)
- [x] Unified diff parser: renames, binary files, mode changes, quoted paths, "no newline" markers, CRLF
- [x] Ref resolution, merge-base, default base discovery, shallow clone detection
- [x] History signals: per-file churn, authors, fix-commit ratio, measured from the base commit's date

Done when: parser tests pass against real `git diff` output produced in temp repos, including awkward file names.

### Segment C: configuration
- [x] `changerisk.toml` and `[tool.changerisk]` in `pyproject.toml`
- [x] Per-rule enable, severity, weight, options; glob lists for ignore, sensitive, tests, generated
- [x] Validation with messages that say what is wrong and suggest the likely fix
- [x] Inline suppression: `changerisk: ignore RULE`

Done when: bad configs produce readable errors; every option is exercised in tests.

### Segment D: rule engine and rules
Rule families (ids are stable and documented in `docs/RULES.md`, generated from the registry):

| Family | Ids | Examples |
|---|---|---|
| Configuration | CFG001-004 | config file edited, debug/TLS flag flipped, timeout or pool size changed by a large factor, `.env` committed |
| Tests | TST001-006 | test file deleted, test cases removed, tests skipped, assertions dropped, source changed with no tests, coverage gate lowered |
| Dependencies | DEP001-004 | manifest changed, major version jump, pin loosened, lockfile not updated |
| Security | SEC001-003 | secret-shaped values (masked in output), auth/payment code touched, certificate checks disabled |
| Pipeline | CI001-003 | workflow edited, checks weakened, permissions or triggers widened, unpinned actions |
| Database | DB001-003 | migration added, destructive statement, applied migration edited |
| Size and shape | SIZ001-003 | large change, change spread over many modules, one huge file diff |
| History | HIS001-002 | hotspot file with a high fix ratio, revert inside the range |
| Interfaces | API001-002 | public function removed or re-signed, API contract file changed |
| Code patterns | COD001-003 | risky calls added, swallowed errors, lint/type checks suppressed |

Each rule carries: id, name, category, default severity, a "why this is risky" paragraph, and "what to test" items. That metadata feeds the report directly.

Done when: every rule has positive, negative, and edge-case tests, and false-positive guards (placeholders, test files, docs) are covered.

### Segment E: scoring and explanation
- [x] Severity points: info 0, low 3, medium 8, high 16, critical 30
- [x] Repeated hits of one rule decay (1, 1/2, 1/4, ...) so ten similar findings do not drown out everything else
- [x] Score = `100 * (1 - exp(-points / 40))`: saturates smoothly, never exceeds 100
- [x] Level bands: <25 low, <50 moderate, <75 high, otherwise critical
- [x] Level floor: any critical finding means at least high; any high finding means at least moderate. This stops the curve from hiding a single severe problem.
- [x] Verdict sentence, recommendation, categorised breakdown, prioritised test plan
- [x] Every finding's displayed points add up to the total (the report can be audited by hand)

Done when: property tests show monotonicity (adding a finding never lowers the score) and the floor rules hold.

### Segment F: reports
- [x] Text (ASCII-safe, optional colour)
- [x] Markdown with a hidden marker so the PR comment is updated in place
- [x] JSON with a versioned schema
- [x] GitHub annotations (capped at the platform limit) and SARIF
- [x] Standalone HTML: the dashboard bundled into one file with the report embedded

Done when: each format has a snapshot-style test and the HTML opens with no network.

### Segment G: CLI
Commands: `analyze`, `serve`, `rules`, `init`, `ci`.
Exit codes: 0 pass, 1 gate tripped, 2 usage or config error, 3 git or runtime failure.

Done when: CLI tests cover each command and each exit code.

### Segment H: GitHub integration
- [x] `changerisk ci`: reads the Actions event, picks base and head, writes the step summary and outputs, emits annotations
- [x] Idempotent PR comment (find by marker, update or create); degrades quietly on forked PRs where the token is read-only
- [x] `action.yml` composite action with inputs and outputs
- [x] Workflows: project CI (matrix on Linux and Windows) and a dogfooding workflow

Done when: event parsing and comment upsert are tested against fakes; workflow files lint as valid YAML.

### Segment I: dashboard backend
- [x] Report store under `.changerisk/` in the repo (self-ignoring)
- [x] Stdlib HTTP server bound to localhost: JSON API, static files, strict CSP
- [x] Hardening: Host header allow-list (DNS rebinding), same-origin check on POST, ref validation, body size cap, path traversal checks

Done when: server tests hit a live instance on an ephemeral port, including hostile requests.

### Segment J: frontend
Design is specific to this subject: a change-review tool for engineers who read diffs all day.
- [x] Design direction and tokens written down first (`docs/DESIGN.md`)
- [x] Risk scale component (a ruler with the gate marked on it), not a generic gauge
- [x] Reasons list ranked by contribution, evidence inline, test focus per reason
- [x] Test plan checklist, file table with change-size bars, diff view with inline annotations
- [x] History trend with the threshold line; rule catalogue
- [x] Light and dark themes designed separately; keyboard and screen-reader support; phone width
- [x] No framework, no build step, no inline styles (works under a strict CSP)

Skills used: `artifact-design` for layout, typography, theming, and the "avoid generic AI look" checks; `dataviz` for the score scale, trend, and breakdown charts (palette validated with its script).

Done when: reviewed in the browser at desktop and phone widths in both themes, after several revision passes.

### Segment K: demo and docs
- [x] `scripts/make_demo_repo.py`: builds a believable service repo with months of history and several branches (one nasty, one clean, some in between) and seeds the dashboard history
- [x] README, ARCHITECTURE, RULES (generated), API, DESIGN, CONTRIBUTING-style notes in the README

### Segment L: verification
- [x] Full pytest run with coverage, ruff clean
- [x] Frontend unit tests via `node --test`
- [x] Wheel builds and contains the frontend
- [x] Manual run against the demo repo: CLI, server, standalone HTML
- [x] Final read-through of every file for leftover rough edges

## 4. Order of work

A -> B -> C -> D (in family batches, tests alongside) -> E -> F (non-HTML) -> G -> H -> I -> J -> F (HTML) -> K -> L.
The frontend waits until the API shape is real, so its mock data is a real report.

## 5. Quality bar

- Code reads like a person wrote it: short functions, comments only where the reason is not obvious, names from the domain.
- Prose in docs and UI is plain. No emoji, no marketing language.
- Rules are conservative. A noisy tool gets ignored, so each rule has guards against its obvious false positives, and findings cite evidence.
- Output never echoes a full secret.

## 6. Risks

| Risk | Handling |
|---|---|
| Regex heuristics misfire | Narrow patterns, skip comments and test fixtures where it makes sense, per-rule disable and inline ignore |
| Shallow CI clones break base lookup and history | Detect shallow repos, say so in the report notes, document `fetch-depth: 0` |
| Large diffs | Size cap on parsed diff, per-file hunk cap in reports, truncation noted in output |
| Windows paths and line endings | CRLF stripped in the parser, POSIX paths in all models, CI matrix includes Windows |
| Local server exposure | Localhost only, Host and Origin checks, CSP, no CORS |

## 7. Outcome

Built and checked. Numbers from the final verification run:

| | |
|---|---|
| Rules | 33 in ten areas, each with tests for hits, near misses and quiet cases |
| Python tests | 423, against real git repositories; 94.85% line and branch coverage (CI gate: 90%) |
| Frontend tests | 15 with `node --test`, plus tests that bundle and syntax-check the real frontend |
| Lint | `ruff check` and `ruff format --check` clean |
| Packaging | wheel builds, contains the dashboard, and an install in a clean environment serves it and produces a byte-identical HTML report |
| Size | about 6,100 lines of backend, 2,900 of dashboard (JS, CSS, HTML), 3,900 of tests |

### What changed from the plan, and why

* **Findings have a scope** (file or whole change). Seen in the first dashboard review: size and spread
  findings were making every file look flagged.
* **Redaction is central.** A test caught a full secret in the report's raw diff lines even though the
  findings had masked it. `redact.py` now runs over everything that leaves the engine.
* **CI reads the configuration from the base branch on pull requests.** Found while reviewing the
  Action: a pull request could otherwise switch off its own gate.
* **Severities were recalibrated** after seeing the demo's scores (see `docs/DESIGN.md`).
* **Added** beyond the plan: a rule reference generated from the registry (with a drift test), export
  endpoints for any saved report, `RiskReport.from_dict`, a lint test for the repo's own workflows,
  and a check that the dashboard's JS thresholds match the Python scoring.
* **E501 is ignored** in lint; `ruff format` owns line length and what it cannot wrap is prose and regexes.

### Not done, on purpose or for lack of means

* The GitHub Action and workflows have not run on GitHub. They are linted, checked against the CLI's
  real flags, and held to ChangeRisk's own pipeline rules by tests, but nothing replaces a first real run.
* Not published to PyPI, and this folder is not a git repository yet.
* A handful of lines are untested: the blocking `serve()` loop, the Windows colour check, and the
  installed-package branch of `web_dir()` (verified by hand with a clean wheel install instead).
* Fonts are the platform's (Bahnschrift on Windows). No font files are bundled, so on macOS and Linux the
  dashboard falls back to the system sans and looks plainer.
