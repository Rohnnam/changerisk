# Hosted mode

`changerisk serve --hosted` runs the dashboard as a public web service instead of a local tool. It
has no repository to look at, so the change comes from one of two places:

* a **pasted diff** (the output of `git diff`, or any pull request's `.diff`), or
* a **public GitHub pull request** (or compare link), which the server fetches from GitHub.

Everything else is the same: the same rules, the same report, the same interface. The local
dashboard (`changerisk serve`) is still the right tool for private repositories, because it reads
the repository directly and also uses commit history, which a diff alone cannot provide.

## What a hosted instance does not do

* **It keeps nothing.** No repository, no stored reports, no database, no log of what was submitted.
  A report exists in the response and in the visitor's browser (local storage), and nowhere else.
* **It cannot see private repositories.** It talks to GitHub without credentials for the visitor, so
  only public pull requests work. Private changes can still be analysed by pasting a diff.
* **It does not use commit history.** Hotspot detection (`HIS001`) needs a local clone, so it is
  skipped. Revert detection (`HIS002`) still works for pull requests, because the commit list is
  fetched. Lockfile checks (`DEP004`) run only when the pull request touches a manifest, using the file
  list GitHub returns. Reports say what was skipped.

## Running it

```bash
pip install .
changerisk serve --hosted --host 0.0.0.0 --port 7860
```

or as a container:

```bash
docker build -t changerisk .
docker run --rm -p 7860:7860 -e GITHUB_TOKEN=ghp_xxx changerisk
```

The image runs as an unprivileged user, has a health check on `/api/health`, and needs no volume.

## Settings

All through environment variables, all optional.

| Variable | Default | Meaning |
|---|---|---|
| `GITHUB_TOKEN` | none | A token with **no scopes** (read-only access to public data). Raises GitHub's limit from 60 to 5,000 requests an hour. A pull request costs 3 to 5 requests. |
| `CHANGERISK_RATE_LIMIT` | 20 | Analyses per visitor per window |
| `CHANGERISK_RATE_WINDOW` | 600 | Window length in seconds |
| `CHANGERISK_MAX_CONCURRENT` | 4 | Analyses running at once; more get a 503 and a retry hint |
| `CHANGERISK_MAX_DIFF_KB` | 2048 | Largest diff accepted |
| `CHANGERISK_CACHE_SECONDS` | 300 | How long a public pull request's result is reused. Pasted diffs are never cached |
| `CHANGERISK_TRUSTED_PROXIES` | 0 | How many reverse proxies sit in front, so the visitor's address is read from `X-Forwarded-For` correctly |
| `CHANGERISK_ALLOWED_ORIGINS` | none | Extra origins allowed to POST (comma separated) |
| `CHANGERISK_FRAME_ANCESTORS` | none | Sites allowed to embed the app in a frame (comma separated) |

Set `CHANGERISK_TRUSTED_PROXIES` to the real number of proxies. Too low and every visitor appears to
share the proxy's address, so one person's requests use up everyone's allowance. Too high and a
visitor can choose the address they are counted under. The first three requests after startup log how
many `X-Forwarded-For` entries arrived (a count only, never an address) so you can check.

## How it is protected

A public service that reads other people's code and talks to another service on their behalf needs
more than a local tool does. What is in place, and where it is tested (`tests/test_hosted.py`,
`tests/test_remote.py`, `tests/test_robustness.py`):

| Risk | Handling |
|---|---|
| Someone stalls the server with hostile input | Diffs over 2 MB are refused, each line is cut at 2,000 characters before any rule sees it, a 25 second budget stops further rules from starting once it is spent, and a measured set of pathological line shapes runs in milliseconds. One of them (a long run of word characters) took 23 seconds before a rule's pattern was fixed; a regression test holds the fix. |
| One visitor uses everything | 20 analyses per 10 minutes per visitor, at most 4 running at once, then 429 or 503 with `Retry-After` |
| The server is used to attack something else | It contacts only `api.github.com` and `raw.githubusercontent.com` over HTTPS, refuses redirects anywhere else, and accepts only strictly parsed GitHub pull request and compare URLs |
| Submitted code ends up somewhere | Nothing is stored or logged. Request bodies are never logged. The proxy check logs counts only. Findings and diff lines are redacted for credentials before leaving the engine |
| Cross-site requests | POSTs must come from the same origin (or a listed one); responses carry a strict content security policy with no inline scripts or styles |
| Being framed by another site | Refused, except by origins in `CHANGERISK_FRAME_ANCESTORS` |
| Spoofed forwarding headers dodge the rate limit | `X-Forwarded-For` is read only through the configured number of trusted proxies |
| Pull request text becomes markup | The dashboard builds every element from text, never from HTML, and only links to `https://github.com/` addresses |
| The GitHub token leaks | It is read from the environment, sent only to the GitHub API, and never returned or logged |

What it does not have: accounts, quotas per user, or abuse detection beyond the rate limit. If you
expose it widely, put it behind a CDN or a proxy that provides those.

## Running with no server: the browser build

Hosting a server costs money and has to be defended. The browser build needs neither. It is the same
engine, compiled to WebAssembly by [Pyodide](https://pyodide.org), running in a Web Worker inside the
page. A pasted diff never leaves the visitor's machine. A pull request is fetched from GitHub by the
visitor's own browser. The host only serves static files, so it can be a free Hugging Face **Static**
Space, GitHub Pages, or any file host.

```
python scripts/build_browser_bundle.py        # the Python package as one JSON file (committed)
python scripts/build_space.py --ref <commit>  # writes dist/space/index.html and README.md
```

`index.html` is the dashboard's page with every asset address pointing at this repository **at that
commit**, through jsDelivr, so a deployed Space never changes under its readers. To release a new
version: commit, build with the new commit's full SHA, upload the two files.

What is different from the hosted server, and why:

| | Hosted server | Browser build |
|---|---|---|
| Where analysis runs | the server | the visitor's browser |
| GitHub limit | one shared allowance (60 an hour, 5,000 with a `GITHUB_TOKEN`) | 60 an hour **per visitor's network**; a token cannot be kept secret in a page, so there is none |
| Rate limits, size caps | enforced by the server | the diff cap and time budget still apply; a visitor can only slow down their own tab |
| HTML export | yes | no (JSON, SARIF and Markdown only; the standalone page needs the server's files) |
| First visit | instant | downloads about 10 MB once (Python and the engine), then the browser caches it |
| Reports | kept in the browser | kept in the browser |

The page's content security policy is set in a `<meta>` tag: no inline scripts, scripts only from the
two pinned jsDelivr paths, network only to those, `api.github.com` and `raw.githubusercontent.com`.
`wasm-unsafe-eval` is allowed because WebAssembly needs it; plain `eval` is not.
`tests/test_space.py` checks the policy, that every address is pinned, and that what the page loads
exists in the repository.

The trust you extend is jsDelivr (serving files at a commit) and Pyodide's release on the same CDN.
Both are pinned by version or commit. A Space has no server to patch and nothing to keep running.

### Creating the Space

1. At huggingface.co/new-space choose **Static** as the SDK, and make it public.
2. Add `README.md` and `index.html` from `dist/space/` at the root (the web editor is enough: both are
   small).
3. Open the Space. The first load fetches Python; later loads are cached.

## Hugging Face Docker Space (needs a paid plan)

Docker Spaces are not available on every account, so this is the alternative for those who have one.
`deploy/hf-space-docker/` holds the two files it needs. The Space installs ChangeRisk from this GitHub
repository at a pinned ref, so the Space repository stays tiny, and it runs the server in this
document, with its rate limits and an optional `GITHUB_TOKEN`.

1. Create a Space at huggingface.co/new-space. Choose **Docker** as the SDK and a blank template.
2. Put `deploy/hf-space-docker/README.md` and `deploy/hf-space-docker/Dockerfile` at the root of the
   Space repository (through the web editor, or by cloning it and pushing).
3. In the Space's settings, add a **secret** named `GITHUB_TOKEN` (optional, but without it GitHub
   allows only 60 requests an hour for the whole Space, shared by every visitor).
4. Open the Space's logs after the first few requests and check the `proxy check` line. If it says
   `has 1 entries, trusting 1` the setting is right. If it says 2 entries, set
   `CHANGERISK_TRUSTED_PROXIES=2` in the Dockerfile.
5. To release a new version, change `CHANGERISK_REF` in the Dockerfile to a tag or commit and push.

Free Spaces go to sleep after a period without visitors and take a short while to wake.

### Why not Streamlit

Streamlit builds interfaces from its own widgets. Using it here would mean rewriting the dashboard
and losing its design (the risk ruler, the diff view with annotations, the checklist), for a worse
result. Both routes above run the real dashboard unchanged.
