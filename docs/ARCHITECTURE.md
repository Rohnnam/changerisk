# Architecture

## The pipeline

```
git repository
   │  gitops.py        run git (argument lists, no shell), resolve refs, merge base
   ▼
unified diff text
   │  diffparse.py     renames, binary files, quoted paths, CRLF, "no newline" markers
   ▼
ChangeSet              files -> hunks -> lines, commits, tracked files, repo name
   │  + config.py      changerisk.toml, validated
   │  + history.py     per-file churn and fix ratio, measured from the base commit's date
   ▼
Context                the view of the change that rules get: classifier, options, suppression
   │  rules/*.py       33 rules in ten modules, each a small class with metadata
   ▼
Findings
   │  redact.py        mask anything credential-shaped, again, before it leaves the engine
   │  scoring.py       points, decay for repeats, score, level, level floor
   │  explain.py       verdict, recommendation, test plan, per-area breakdown
   ▼
RiskReport             the one object everything downstream consumes (engine.py)
   ├── reports/text.py, markdown.py, annotate.py (GitHub annotations, SARIF), html.py
   ├── store.py        JSON files under .changerisk/ in the repository
   ├── server.py       the dashboard's HTTP API and static files
   └── github.py       event handling, PR comment upsert, step summary and outputs
```

`engine.analyze()` is the single entry point. The CLI, the server and the Action all call it.

## Decisions worth knowing about

**Standard library only.** A CI tool should install in a second and never fail because a transitive
dependency moved. The HTTP server is `http.server`, config is `tomllib`, the GitHub API is
`urllib`. The cost is that the server is plain and synchronous, which is fine for one developer on
localhost.

**The report is the product, so rules carry their own explanation.** Every rule is a `RuleInfo`
(id, name, area, default severity, what it looks for, why it matters, what to test) plus a
`check(ctx)` that yields findings. The "why" and "what to test" text feeds the report directly, the
rule reference (`docs/RULES.md` is generated from the registry), and the dashboard's rule list. Test
suggestions can use `{path}` and `{paths}` placeholders, so the checklist says "Start the service
with config/production.yml" and not "start the service with the changed file".

**Scoring is small enough to audit.** Points by severity, half for each repeat of a rule, one
saturating curve, and a floor so a single serious finding cannot be averaged away. The points on each
finding sum exactly to the total, and a test checks that. See `scoring.py`.

**Deterministic, offline, reproducible.** No model calls and no clock in the analysis. History is
measured relative to the base commit's date, not today's, so the same range gives the same report
next month.

**Redaction in two places.** Rules mask what they quote. Separately, `redact.py` runs over every
finding and every diff line that goes into a report. A new rule that forgets to mask still cannot leak
a key. Env files never show values at all. This was added after a test showed the raw diff lines in
the report carried a full secret that the findings had masked.

**A change cannot configure its own review.** In CI on a pull request, `changerisk ci` reads
`changerisk.toml` from the base commit (`config.config_at_ref`). Otherwise a pull request could set
`fail_on = "never"` or ignore every path and pass. Local runs and pushes use the checked-out file,
because there the config is the author's own.

**A broken rule does not break the gate.** `engine.run_rules` catches exceptions per rule, prints
them to stderr, and records a note in the report. The remaining rules still run.

**The frontend has no build step.** Plain ES modules, written in a restricted syntax (single-line
named imports and exports) so `webassets.bundle_js` can fold them into one script. That bundler is
what makes the standalone HTML report possible, and the dashboard's code is checked against the
syntax rules by a test.

## Where the pieces live

| Concern | Files |
|---|---|
| Data shapes | `models.py` |
| Git | `gitops.py`, `diffparse.py`, `history.py` |
| File classification | `paths.py` (globs, test/config/lockfile/generated detection) |
| Configuration | `config.py` |
| Rules | `rules/base.py` (registry and context), `rules/<area>.py` |
| Scoring and wording | `scoring.py`, `explain.py` |
| Orchestration | `engine.py` |
| Output | `reports/` |
| Persistence | `store.py` |
| Dashboard server | `server.py` (shared base and the local app), `webassets.py` |
| Hosted mode | `remote.py` (pasted diffs and GitHub), `hosted.py` (stateless app, limits), `Dockerfile`, `deploy/` |
| GitHub | `github.py`, `action.yml` |
| CLI | `cli.py` |

## Adding a rule

1. Pick the module in `rules/` that matches the area (or add one and list it in `rules/__init__.py`).
2. Describe it:

   ```python
   ABC001 = RuleInfo(
       id="ABC001",
       name="Something risky",
       category="code",
       severity=Severity.MEDIUM,
       summary="What it looks for, in one line.",
       why="Why that is a problem, in two sentences.",
       tests=("What to do about {path}",),
       options={"threshold": 10},  # optional; becomes configurable
   )
   ```
3. Implement it. Use `ctx.added(fc, rule_id)` for added lines so inline ignores work, guard against
   comments, tests and docs where it makes sense, and quote evidence with `evidence()`:

   ```python
   @register
   class Something(Rule):
       info = ABC001

       def check(self, ctx):
           for fc in ctx.files:
               hits = [ln for ln in ctx.added(fc, self.info.id) if "danger" in ln.text]
               if hits:
                   yield ctx.finding(
                       self.info,
                       detail=f"{fc.path} adds a dangerous call.",
                       paths=[fc.path],
                       evidence=[evidence(fc.path, ln.new_no, ln.text) for ln in hits],
                   )
   ```
4. Test it with `tests/helpers.py`: `change({"path": (before, after)})` builds a change from text,
   and `run_rule("ABC001", change)` runs it. Cover the positive case, the near misses, and the places
   it must stay quiet.
5. Run `python scripts/gen_rules_doc.py`. A test fails if you forget.

Use `scope="change"` for findings about the change as a whole (size, spread) so they are not charged
to individual files.

## Hosted mode

The local dashboard owns a repository. The hosted one (`hosted.py`) owns nothing: the change comes from
`remote.py` as a `ChangeSet` built from diff text, so the engine, rules, scoring and reports are the
same code. What differs is everything around it. History and (mostly) the file list are unavailable, so
those rules stay quiet and the report says why. Reports are kept by the browser (`local-store.js`), and
exports are rendered from the report the browser sends back (`POST /api/render`). The frontend picks its
interface from `GET /api/repo` (`hosted: true`) through a small `backend` object, so the views are
shared. [DEPLOY.md](DEPLOY.md) has the threat model.

Getting a change from the network is the new risk, so `remote.py` is strict: it talks to two fixed
hosts, parses URLs with anchored patterns, caps sizes, and never lets a rule see an unbounded line.
Measuring it showed that a secret-detection pattern was quadratic on long runs of word characters
(a minified bundle triggered it too); `tests/test_robustness.py` keeps it fixed.

## The dashboard server

Localhost only by default. It checks the `Host` header (DNS rebinding), refuses cross-origin writes,
validates refs before git sees them (a ref starting with `-` is never passed on), caps request bodies,
refuses paths outside the frontend directory and dotfiles, and sends a strict content security policy
(`default-src 'self'`; no inline scripts or styles). The dashboard is written to run under it: styles
that depend on data are set through CSS custom properties, not inline `style` attributes. Binding to
another address prints a warning, because there is no login.
