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

## Summary

| Id | Name | Area | Default severity |
|---|---|---|---|
| [API001](#api001) | Public interface changed | Interfaces | medium |
| [API002](#api002) | API contract changed | Interfaces | medium |
| [CFG001](#cfg001) | Configuration changed | Configuration | low |
| [CFG002](#cfg002) | Safety setting flipped | Configuration | high |
| [CFG003](#cfg003) | Operational limit changed sharply | Configuration | medium |
| [CFG004](#cfg004) | Environment file tracked | Configuration | high |
| [CI001](#ci001) | Pipeline definition changed | Pipeline | medium |
| [CI002](#ci002) | Pipeline checks weakened | Pipeline | high |
| [CI003](#ci003) | Workflow permissions or triggers widened | Pipeline | medium |
| [COD001](#cod001) | Risky call added | Code patterns | medium |
| [COD002](#cod002) | Error handling reduced | Code patterns | medium |
| [COD003](#cod003) | Checks suppressed | Code patterns | low |
| [DB001](#db001) | Schema migration added | Database | medium |
| [DB002](#db002) | Destructive schema statement | Database | high |
| [DB003](#db003) | Applied migration edited | Database | high |
| [DEP001](#dep001) | Dependencies changed | Dependencies | low |
| [DEP002](#dep002) | Major version change | Dependencies | medium |
| [DEP003](#dep003) | Version pin loosened | Dependencies | medium |
| [DEP004](#dep004) | Lockfile not updated | Dependencies | medium |
| [HIS001](#his001) | Frequently changed file | History | medium |
| [HIS002](#his002) | Revert in the range | History | low |
| [SEC001](#sec001) | Possible secret committed | Security | high |
| [SEC002](#sec002) | Sensitive area modified | Security | medium |
| [SEC003](#sec003) | Certificate or signature checks disabled | Security | high |
| [SIZ001](#siz001) | Large change | Size and spread | medium |
| [SIZ002](#siz002) | Change spans many areas | Size and spread | medium |
| [SIZ003](#siz003) | Very large single-file change | Size and spread | medium |
| [TST001](#tst001) | Test file deleted | Tests | high |
| [TST002](#tst002) | Test cases removed | Tests | medium |
| [TST003](#tst003) | Tests disabled | Tests | medium |
| [TST004](#tst004) | Assertions removed | Tests | medium |
| [TST005](#tst005) | Source changed without tests | Tests | medium |
| [TST006](#tst006) | Coverage gate lowered | Tests | medium |

## Configuration

### CFG001
**Configuration changed**. Default severity: low.

*Looks for:* A configuration file was edited, added or removed. Production files rank one step higher.

*Why it matters:* Configuration is not covered by unit tests. A wrong value passes CI and only fails when a real environment loads it, usually under production traffic.

*What to test:*

- Start the service with {path} and run its smoke tests
- Diff the effective settings from {path} against the previous release in staging

### CFG002
**Safety setting flipped**. Default severity: high.

*Looks for:* Debug switched on, or TLS, auth, CSRF or validation switched off, or access opened to '*'.

*Why it matters:* These switches exist to protect users and data. Flipping one is easy to do for a quick local test and easy to forget about in a merge.

*What to test:*

- Confirm the new value in {path} is intended for every environment that reads it
- Exercise the protected path (login, TLS handshake, CSRF check) and confirm it still rejects bad input

### CFG003
**Operational limit changed sharply**. Default severity: medium.

*Looks for:* A timeout, pool size, retry count, rate or similar limit moved by a large factor.

*Why it matters:* Limits tune how the system behaves under stress. A tenfold timeout hides slow dependencies, a pool that is too large exhausts the database, and a value of zero often means unlimited.

*What to test:*

- Load test with the new values in {path} and watch connection counts, queue depth and latency
- Fail a dependency on purpose (slow it down, drop it) and check how the service reacts

*Options:*

- `factor` (default `2.0`)

### CFG004
**Environment file tracked**. Default severity: high.

*Looks for:* A real .env file (not an example or template) is part of the change.

*Why it matters:* Environment files usually hold credentials. Once one is committed, its values live in history even after the file is deleted.

*What to test:*

- Rotate any credential that appeared in the file
- Move the values to a secret store and commit only a .env.example

## Tests

### TST001
**Test file deleted**. Default severity: high.

*Looks for:* A whole test file was removed and its cases do not reappear elsewhere.

*Why it matters:* Tests are the record of behaviour the team decided to keep. Deleting a file removes that protection for every later change, and nothing fails to tell anyone.

*What to test:*

- For each case deleted with {path}, name where the behaviour is now covered, or confirm it was removed on purpose
- Run the old {path} against the new code to see what it would have caught

### TST002
**Test cases removed**. Default severity: medium.

*Looks for:* Test cases were deleted from a test file that stays.

*Why it matters:* Removing a case is how a failing test gets 'fixed' without fixing the code. Even when it is legitimate, the behaviour it checked is now unguarded.

*What to test:*

- Read each case removed from {path} and confirm the behaviour it checked is gone or covered elsewhere
- Check the coverage report for lines that only the removed cases reached

*Options:*

- `high_at` (default `3`)

### TST003
**Tests disabled**. Default severity: medium.

*Looks for:* Skip, xfail, ignore or focus (.only) markers were added to tests.

*Why it matters:* A skipped test reports nothing, and a focused test (.only) silently skips all the rest. Both leave the build green while coverage drops.

*What to test:*

- Run the disabled tests in {path} by hand and record whether they pass
- Add a ticket or deadline to every skip so it does not become permanent

### TST004
**Assertions removed**. Default severity: medium.

*Looks for:* Tests keep their names but check less than before.

*Why it matters:* A test with fewer assertions still passes while verifying less. This is the quietest way to lose coverage.

*What to test:*

- Compare the old and new assertions in {path} case by case
- Mutate the code under test (flip a condition) and confirm the weakened tests still fail

*Options:*

- `min_drop` (default `3`)

### TST005
**Source changed without tests**. Default severity: medium.

*Looks for:* Substantial source changes and no test file was touched.

*Why it matters:* New behaviour with no test is unproven, and changed behaviour with no test change means either the old tests were already vague or they are not running against this code.

*What to test:*

- Add a test for each changed code path, starting with the largest file in the change
- Run the existing suite with coverage and check the changed lines are actually executed

*Options:*

- `min_lines` (default `20`)
- `high_lines` (default `200`)

### TST006
**Coverage gate lowered**. Default severity: medium.

*Looks for:* A minimum-coverage threshold was reduced or removed.

*Why it matters:* A coverage gate is a promise that new code is tested. Lowering it is usually done to get a build through, and the gap then stays.

*What to test:*

- Run coverage on the base and head commits and compare the totals
- Restore the threshold and add the missing tests instead, if the drop is small

## Dependencies

### DEP001
**Dependencies changed**. Default severity: low.

*Looks for:* Packages were added, removed or re-versioned in a manifest.

*Why it matters:* Every dependency is code you did not write and cannot fully review. New packages bring their own bugs, licences and transitive dependencies.

*What to test:*

- Install from a clean environment using {path} and run the full suite
- Read the release notes of every changed package

*Options:*

- `many` (default `5`)

### DEP002
**Major version change**. Default severity: medium.

*Looks for:* A dependency moved to a different major version, or was downgraded.

*Why it matters:* Major versions are where breaking changes live. Downgrades are rarer and often mean something broke and was rolled back by hand.

*What to test:*

- Read the upgrade guide and search the code for each deprecated API it lists
- Run the integration tests, not just unit tests, against the new version

### DEP003
**Version pin loosened**. Default severity: medium.

*Looks for:* An exact version was replaced by a range or removed.

*Why it matters:* A pinned version builds the same way every time. A range means the next install can pick up a release nobody on the team has tried.

*What to test:*

- Install twice a week apart and compare the resolved versions
- Pin it again, or add a lockfile, unless the range is deliberate

### DEP004
**Lockfile not updated**. Default severity: medium.

*Looks for:* Dependencies changed in a manifest but the lockfile next to it did not.

*Why it matters:* CI and teammates install from the lockfile. If it disagrees with the manifest, they get different packages from the ones this change was written against.

*What to test:*

- Regenerate the lockfile next to {path} and commit it
- Run the install step in CI in frozen-lockfile mode to confirm they agree

## Security

### SEC001
**Possible secret committed**. Default severity: high.

*Looks for:* A value shaped like a credential, or a private key file, was added.

*Why it matters:* A committed credential is exposed to everyone with read access to the repository, now and in every clone, and stays in history after it is removed.

*What to test:*

- Treat the credential as leaked: revoke and rotate it before merging
- Load the value from the environment or a secret store, and scan history with a secret scanner

### SEC002
**Sensitive area modified**. Default severity: medium.

*Looks for:* Code for authentication, sessions, permissions, crypto or payments changed.

*Why it matters:* Bugs in these areas are security incidents or lost money, not just defects, and they rarely show up in happy-path tests.

*What to test:*

- Test the negative paths: expired and forged tokens, missing permissions, replayed requests
- Ask a second reviewer who knows this area to read the changes in {paths}

*Options:*

- `high_lines` (default `80`)

### SEC003
**Certificate or signature checks disabled**. Default severity: high.

*Looks for:* TLS verification, host key checking or similar was switched off in code.

*Why it matters:* Turning verification off lets anyone on the network path impersonate the server. It is usually added to get past a local certificate error and then ships.

*What to test:*

- Connect with an untrusted certificate and confirm the call fails
- Fix the certificate chain instead of disabling the check

## Pipeline

### CI001
**Pipeline definition changed**. Default severity: medium.

*Looks for:* A CI/CD workflow or pipeline file was edited.

*Why it matters:* The pipeline is what decides whether every other change is safe to merge and ship. A mistake here can pass broken code or block the whole team, and the change itself is hard to test before it runs for real.

*What to test:*

- Run the workflow in {path} on a branch and read the logs, not just the final status
- Check that a deliberately failing test still turns the pipeline red

### CI002
**Pipeline checks weakened**. Default severity: high.

*Looks for:* Failures are ignored, a step is disabled, or a test or lint step was removed.

*Why it matters:* A pipeline that cannot fail is decoration. These edits keep the build green while the code underneath gets less checked.

*What to test:*

- Push a commit with a failing test and confirm the pipeline fails
- Compare the list of steps before and after and account for each missing one

### CI003
**Workflow permissions or triggers widened**. Default severity: medium.

*Looks for:* Broader token permissions, risky triggers, or actions pinned to a moving branch.

*Why it matters:* Workflows run with a token and secrets. Wider permissions, triggers that run untrusted pull request code with secrets, and unpinned third-party actions are how pipelines get used against their owners.

*What to test:*

- Read the permissions block and remove anything the job does not need
- Pin third-party actions to a commit SHA

## Database

### DB001
**Schema migration added**. Default severity: medium.

*Looks for:* A new migration file was added.

*Why it matters:* A migration changes shared state that cannot be rolled back by redeploying the previous version, and it runs against data volumes the test database never had.

*What to test:*

- Run {path} against a copy of production-sized data and time it
- Run the previous application version against the migrated schema (rolling deploys do this)
- Write down and rehearse the rollback

### DB002
**Destructive schema statement**. Default severity: high.

*Looks for:* Drops, truncates, unqualified deletes, renames, type changes, or NOT NULL without a default.

*Why it matters:* These statements lose data, lock large tables, or break the version of the application that is still running during the deploy.

*What to test:*

- Take a backup and restore it into a scratch database before running {path}
- Check that no running code still reads the dropped or renamed column
- Use expand-and-contract: add the new shape, migrate readers, then remove the old one

### DB003
**Applied migration edited**. Default severity: high.

*Looks for:* A migration that already existed was modified, renamed or deleted.

*Why it matters:* Databases that already ran the old version will not run it again, so environments drift apart silently and the history no longer describes any real database.

*What to test:*

- Put the change in a new migration instead
- Compare the schema of a freshly migrated database with one migrated before this change

## Size and spread

### SIZ001
**Large change**. Default severity: medium.

*Looks for:* Many lines changed, not counting docs, lockfiles and generated files.

*Why it matters:* Review quality drops sharply with size, and large changes mix several ideas so a regression is hard to trace to its cause.

*What to test:*

- Split the change into independent pieces and test each on its own
- Run the full suite and an exploratory pass over the features it touches

*Options:*

- `medium_lines` (default `400`)
- `high_lines` (default `1000`)

### SIZ002
**Change spans many areas**. Default severity: medium.

*Looks for:* Files in many different top-level modules changed together.

*Why it matters:* A change that reaches across modules is more likely to break an assumption one of them makes about another.

*What to test:*

- Run integration tests that cross the touched module boundaries
- Ask an owner of each area to check their part

*Options:*

- `areas` (default `5`)

### SIZ003
**Very large single-file change**. Default severity: medium.

*Looks for:* One file has a very large diff.

*Why it matters:* A diff that big in one file is hard to read in a review tool, and reviewers tend to skim it.

*What to test:*

- Read the file top to bottom instead of the diff
- Check that every public function in it still has a test

*Options:*

- `file_lines` (default `300`)

## History

### HIS001
**Frequently changed file**. Default severity: medium.

*Looks for:* A file in the change was edited often and fixed often in the weeks before.

*Why it matters:* Files that change a lot and keep needing fixes are where defects concentrate. Another edit has a higher chance of being the next fix.

*What to test:*

- Read the recent fix commits for this file and check this change does not repeat their mistakes
- Add a regression test for each previous bug fix that has none

*Options:*

- `commits` (default `8`)
- `fix_ratio` (default `0.4`)
- `max_findings` (default `4`)

### HIS002
**Revert in the range**. Default severity: low.

*Looks for:* The commits include a revert, or a re-application of reverted work.

*Why it matters:* A revert means something was released or merged and then pulled back. Bringing the same change in again tends to reintroduce the original problem.

*What to test:*

- Find out why the original change was reverted and write a test for that failure
- Re-run whatever scenario triggered the revert

## Interfaces

### API001
**Public interface changed**. Default severity: medium.

*Looks for:* A public function or class was removed or given a different signature.

*Why it matters:* Callers outside the file, and outside the repository, depend on the old signature. Nothing in this diff shows who they are.

*What to test:*

- Search the codebase and dependent repositories for callers of each changed symbol
- Keep the old name working for one release with a deprecation warning

*Options:*

- `many` (default `5`)

### API002
**API contract changed**. Default severity: medium.

*Looks for:* An OpenAPI, protobuf, GraphQL or Avro schema changed.

*Why it matters:* Contracts are shared with clients that deploy on their own schedule. Removing or renumbering a field breaks them without any error on this side.

*What to test:*

- Run contract tests or a schema diff tool (such as buf breaking or oasdiff) against the previous version
- Test an old client against the new server

## Code patterns

### COD001
**Risky call added**. Default severity: medium.

*Looks for:* eval/exec, unsafe deserialisation, shell=True, string-built SQL, raw HTML injection.

*Why it matters:* These calls turn data into behaviour. When the data comes from a user, a file or a network peer, they become injection or remote-code-execution holes.

*What to test:*

- Trace where each argument comes from and test with hostile input (quotes, newlines, ../, <script>)
- Replace with the safe alternative (parameterised queries, argument lists, json/safe_load, textContent)

### COD002
**Error handling reduced**. Default severity: medium.

*Looks for:* Errors are swallowed by empty handlers, or try/catch blocks were removed.

*Why it matters:* An error that is caught and ignored turns a loud failure into silent wrong results, which are far harder to find in production.

*What to test:*

- Make the dependency fail on purpose and check the user sees an error and a log line appears
- Check callers still handle the failure the removed code used to deal with

### COD003
**Checks suppressed**. Default severity: low.

*Looks for:* noqa, type: ignore, eslint-disable, nosec and similar markers were added.

*Why it matters:* Each suppression hides a warning someone decided to see. One is routine; several in one change usually mean the warnings were in the way.

*What to test:*

- Remove each suppression and read the warning it was hiding
- Confirm the reason is written next to every suppression that stays

*Options:*

- `many` (default `5`)
