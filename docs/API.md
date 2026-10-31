# Dashboard API and report format

The dashboard is a thin client over this API, and `changerisk analyze -f json` prints the same
report object, so scripts can use either.

All endpoints are JSON unless noted. Errors look like `{"error": "message"}` with a suitable status.
Requests need a `Host` header naming the address the server is listening on. Writes need
`Content-Type: application/json` and, when an `Origin` header is sent, the same origin.

## Endpoints

| Method and path | Purpose |
|---|---|
| `GET /api/health` | `{"ok": true, "version": "..."}` |
| `GET /api/repo` | Repository name, current branch, default base, refs (with kind: `branch`, `remote` or `tag`), recent commits, shallow-clone flag, config file in use |
| `GET /api/rules` | Every rule with its metadata, the severity and options in effect, and whether it is enabled |
| `GET /api/reports` | Summaries of saved reports, newest first |
| `GET /api/reports/{id}` | One full report |
| `DELETE /api/reports/{id}` | Remove a saved report |
| `GET /api/reports/{id}/export?format=F` | A saved report as `html`, `json`, `markdown`, `sarif` or `text`, sent as a download |
| `POST /api/analyze` | Run an analysis, save it, and return it |

`POST /api/analyze` body, all keys optional:

```json
{
  "mode": "range",          // "range" (default), "staged" or "worktree"
  "base": "main",           // range mode; defaults to the repository's main branch
  "head": "my-branch",      // range mode; defaults to HEAD
  "history": true           // include commit-history signals; defaults to the config
}
```

| Status | When |
|---|---|
| 400 | A field has the wrong type or value, or a ref is not a usable revision |
| 403 | Unexpected `Host`, or a cross-origin or cross-site write |
| 413 | Body over 64 KB |
| 415 | Not `application/json` |
| 422 | git could not do it (unknown revision, no shared history) or the config is invalid |

Static files are served from `/`. Anything else is a 404.

## Report object (`changerisk.report/1`)

```jsonc
{
  "schema": "changerisk.report/1",
  "id": "20260914-011200-52c840a",      // null until saved
  "tool_version": "0.1.0",
  "generated_at": "2026-09-14T01:12:00+00:00",
  "repo": "ledgerline",
  "range": {
    "mode": "range",                     // or "staged", "worktree"
    "base": "main", "head": "feature/faster-checkout",
    "base_sha": "...", "head_sha": "...", "merge_base": "..."
  },
  "stats": { "files": 12, "additions": 35, "deletions": 67, "commits": 8 },
  "score": 100,                          // 0-100
  "points": 337.2,                       // the sum behind the score
  "level": "critical",                   // low | moderate | high | critical
  "floor_note": null,                    // set when the level was raised by a severe finding
  "verdict": "Do not merge until ...",
  "recommendation": "Hold the merge. ...",
  "gate": { "fail_on": "high", "failed": true, "reason": "Risk level critical reached the gate (high)." },
  "findings": [
    {
      "id": "f1", "rule": "CFG002", "scope": "file",   // or "change"
      "category": "config", "title": "Safety setting flipped",
      "severity": "critical",           // info | low | medium | high | critical
      "points": 30.0,                   // after decay for repeats; these sum to `points`
      "detail": "config/production.yml: debug was switched on; ...",
      "paths": ["config/production.yml"],
      "evidence": [
        { "path": "config/production.yml", "line": 3, "text": "  debug: true", "side": "new" }
      ],
      "why": "These switches exist to protect users ...",
      "test_focus": ["Confirm debug stays off in every environment ..."]
    }
  ],
  "categories": [ { "id": "config", "label": "Configuration", "points": 80.2, "findings": 7, "top_severity": "critical" } ],
  "test_plan": [ { "text": "Treat the credential as leaked ...", "priority": 1, "rules": ["SEC001"] } ],
  "files": [
    {
      "path": "config/production.yml", "old_path": null, "status": "modified",
      "additions": 6, "deletions": 6, "binary": false,
      "points": 54.7, "findings": ["f1", "f4"],
      "hunks": [ { "old_start": 1, "new_start": 1, "header": "", "lines": [[" ", 1, 1, "service:"], ["-", 3, null, "  debug: false"], ["+", null, 3, "  debug: true"]] } ],
      "truncated": false          // present with hunks; diffs are kept only for files with findings
    }
  ],
  "commits": [ { "sha": "...", "author": "...", "date": "...", "subject": "..." } ],
  "notes": [ "4 more suggested checks are listed on the individual findings." ]
}
```

Notes:

* `evidence[].side` says which side of the diff the line number refers to: `"new"` for an added
  line, `"old"` for a removed one.
* Diff lines are `[kind, old_line, new_line, text]`, where `kind` is `" "`, `"+"` or `"-"`.
* Credential-shaped values are masked or replaced with `<hidden>` everywhere in the object.
* New keys may be added within version 1. Removing or renaming one will bump the schema.
