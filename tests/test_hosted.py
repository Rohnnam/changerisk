import http.client
import json
import threading

import pytest

from changerisk import gitops, hosted
from changerisk.hosted import HostedApp, HostedSettings, RateLimiter, TTLCache
from changerisk.remote import GitHub

from .test_engine import STRIPE, risky_branch, seeded
from .test_remote import FakeGitHub, pull_routes

JSON = {"content-type": "application/json", "host": "changerisk.example"}


@pytest.fixture
def diff_text(repo):
    seeded(repo)
    risky_branch(repo)
    return repo.git("diff", "main", "feature/speedup")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make_app(**kw):
    settings = HostedSettings(**{"rate_limit": 100, **kw.pop("settings", {})})
    return HostedApp(settings, **kw)


def post(app, path, payload, headers=None, peer="9.9.9.9"):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    res = app.handle("POST", path, {**JSON, **(headers or {})}, body, peer)
    ctype = res.headers.get("Content-Type", "")
    return res, json.loads(res.body) if ctype.startswith("application/json") else res.body.decode()


def diff_source(text):
    return {"source": {"type": "diff", "text": text}}


# --- what it offers ---------------------------------------------------------------


def test_info_and_rules_need_no_repository():
    app = make_app()
    res = app.handle("GET", "/api/repo", {"host": "x"})
    info = json.loads(res.body)
    assert (
        info["hosted"] is True
        and info["limits"]["max_diff_kb"] >= 1
        and info["github_token"] is False
    )
    assert len(json.loads(app.handle("GET", "/api/rules", {"host": "x"}).body)["rules"]) == 33
    assert json.loads(app.handle("GET", "/api/health", {"host": "x"}).body)["hosted"] is True


def test_local_only_endpoints_do_not_exist():
    app = make_app()
    for path in ("/api/reports", "/api/reports/abc", "/api/reports/abc/export"):
        assert app.handle("GET", path, {"host": "x"}).status == 404
    assert app.handle("DELETE", "/api/reports/abc", {"host": "x"}).status == 405
    assert app.handle("PUT", "/api/analyze", {"host": "x"}).status == 405


def test_it_never_touches_git_or_the_disk(diff_text, monkeypatch, tmp_path_factory):
    cwd = tmp_path_factory.mktemp("cwd")

    def boom(*a, **k):
        raise AssertionError("hosted mode must not run git")

    monkeypatch.setattr(gitops, "run_git", boom)
    monkeypatch.chdir(cwd)
    res, report = post(make_app(), "/api/analyze", diff_source(diff_text))
    assert res.status == 200 and report["level"] == "critical"
    assert list(cwd.iterdir()) == []  # no .changerisk folder, nothing written


# --- analysing a pasted diff --------------------------------------------------------------


def test_pasted_diff_report(diff_text):
    res, report = post(make_app(), "/api/analyze", diff_source(diff_text))
    assert res.status == 200 and res.headers["Cache-Control"] == "no-store"
    assert report["range"]["mode"] == "diff" and report["id"] is None
    assert report["source"] == {"type": "diff", "label": "pasted diff"}
    assert any("pasted diff" in n for n in report["notes"])
    assert report["gate"]["fail_on"] == "high" and report["gate"]["failed"] is True
    assert STRIPE not in json.dumps(report)  # still redacted
    assert {f["rule"] for f in report["findings"]} >= {"CFG002", "TST001", "SEC001"}


def test_gate_can_be_changed_per_request(diff_text):
    _, report = post(make_app(), "/api/analyze", {**diff_source(diff_text), "fail_on": "never"})
    assert report["gate"] == {"fail_on": "never", "failed": False, "reason": "The gate is off."}


@pytest.mark.parametrize(
    ("payload", "status", "fragment"),
    [
        ({}, 400, "send a source"),
        ({"source": "x"}, 400, "send a source"),
        ({"source": {"type": "diff", "text": "hello"}}, 400, "does not look like a git diff"),
        ({"source": {"type": "diff", "text": ""}}, 400, "no diff to analyse"),
        ({"source": {"type": "ftp"}}, 400, "pasted diff or a GitHub"),
        ({"source": {"type": "github", "url": "nope"}}, 400, "public GitHub pull request"),
        ({"source": {"type": "diff", "text": "x"}, "fail_on": "sometimes"}, 400, "fail_on must be"),
    ],
)
def test_input_validation(payload, status, fragment):
    res, data = post(make_app(), "/api/analyze", payload)
    assert res.status == status and fragment in data["error"]


def test_body_must_be_json():
    app = make_app()
    assert post(app, "/api/analyze", b"{nope")[0].status == 400
    assert post(app, "/api/analyze", b"[1]")[0].status == 400
    assert (
        app.handle(
            "POST", "/api/analyze", {"host": "x", "content-type": "text/plain"}, b"{}"
        ).status
        == 415
    )
    assert app.handle("GET", "/api/analyze", {"host": "x"}).status == 405


# --- GitHub pull requests ----------------------------------------------------------------------


def github_with(diff_text):
    class Transport(FakeGitHub):
        def __call__(self, url, headers):
            if url.endswith("/pulls/7") and "v3.diff" in headers.get("Accept", ""):
                self.calls.append(url)
                return 200, {}, diff_text.encode()
            return super().__call__(url, headers)

    transport = Transport(pull_routes(diff_text))
    return transport, (lambda: GitHub(transport=transport))


def test_pull_request_analysis_and_caching(diff_text):
    transport, factory = github_with(diff_text)
    app = make_app(github=factory)
    payload = {"source": {"type": "github", "url": "https://github.com/acme/ledger/pull/7"}}

    res, report = post(app, "/api/analyze", payload)
    assert res.status == 200 and report["range"]["mode"] == "pr"
    assert report["source"]["title"] == "Speed up checkout" and report["repo"] == "acme/ledger"
    calls = len(transport.calls)
    assert calls >= 3

    again, same = post(
        app,
        "/api/analyze",
        {"source": {"type": "github", "url": "HTTPS://github.com/acme/ledger/pull/7"}},
    )
    assert again.status == 200 and same == report
    assert len(transport.calls) == calls  # served from the short cache, no GitHub calls


def test_pasted_diffs_are_never_cached(diff_text):
    app = make_app()
    post(app, "/api/analyze", diff_source(diff_text))
    assert app._cache._items == {}


def test_github_problems_reach_the_user_with_the_right_status():
    def factory():
        return GitHub(transport=lambda url, headers: (404, {}, b"{}"))

    res, data = post(
        make_app(github=factory),
        "/api/analyze",
        {"source": {"type": "github", "url": "acme/ledger#1"}},
    )
    assert res.status == 404 and "Only public repositories" in data["error"]


# --- protecting a public server --------------------------------------------------------------------


def test_rate_limit_is_per_visitor(diff_text):
    clock = Clock()
    app = HostedApp(HostedSettings(rate_limit=2, rate_window=600), clock=clock)
    assert post(app, "/api/analyze", diff_source(diff_text), peer="1.1.1.1")[0].status == 200
    assert post(app, "/api/analyze", diff_source(diff_text), peer="1.1.1.1")[0].status == 200
    res, data = post(app, "/api/analyze", diff_source(diff_text), peer="1.1.1.1")
    assert (
        res.status == 429 and int(res.headers["Retry-After"]) > 0 and "Slow down" in data["error"]
    )
    assert post(app, "/api/analyze", diff_source(diff_text), peer="2.2.2.2")[0].status == 200
    clock.now += 700
    assert post(app, "/api/analyze", diff_source(diff_text), peer="1.1.1.1")[0].status == 200


def test_rate_limiter_window_and_key_pruning():
    clock = Clock()
    rl = RateLimiter(2, 10, clock)
    assert rl.check("a") == (True, 0) and rl.check("a") == (True, 0)
    allowed, wait = rl.check("a")
    assert not allowed and 1 <= wait <= 11
    clock.now += 11
    assert rl.check("a")[0]
    rl.MAX_KEYS = 3
    for k in "bcdef":
        rl.check(k)
    clock.now += 50
    rl.check("z")
    assert len(rl._hits) <= 2


def test_forwarded_for_is_only_trusted_through_known_proxies():
    behind = make_app(settings={"trusted_proxies": 1})
    assert behind.client_key({"x-forwarded-for": "6.6.6.6, 5.5.5.5"}, "10.0.0.1") == "5.5.5.5"
    assert behind.client_key({"x-forwarded-for": "6.6.6.6"}, "10.0.0.1") == "6.6.6.6"
    assert behind.client_key({"x-forwarded-for": "not-an-ip"}, "10.0.0.1") == "10.0.0.1"
    assert behind.client_key({}, "10.0.0.1") == "10.0.0.1"
    direct = make_app()
    assert (
        direct.client_key({"x-forwarded-for": "6.6.6.6"}, "10.0.0.1") == "10.0.0.1"
    )  # spoofing does nothing


def test_spoofed_forwarding_headers_do_not_buy_extra_requests(diff_text):
    app = HostedApp(HostedSettings(rate_limit=1, trusted_proxies=1))
    for i in range(3):
        res, _ = post(
            app,
            "/api/analyze",
            diff_source(diff_text),
            headers={"x-forwarded-for": f"7.7.7.{i}, 5.5.5.5"},
        )
    assert res.status == 429  # the proxy-added address is what counts


def test_server_busy_when_all_slots_are_taken(diff_text):
    app = HostedApp(HostedSettings(rate_limit=100, max_concurrent=1))
    assert app._slots.acquire(blocking=False)
    res, data = post(app, "/api/analyze", diff_source(diff_text))
    assert res.status == 503 and res.headers["Retry-After"] == "5" and "busy" in data["error"]
    app._slots.release()
    assert post(app, "/api/analyze", diff_source(diff_text))[0].status == 200
    assert app._slots.acquire(blocking=False)  # and the slot is released after an analysis


def test_a_failed_analysis_still_releases_its_slot():
    app = HostedApp(HostedSettings(rate_limit=100, max_concurrent=1))
    for _ in range(3):
        assert post(app, "/api/analyze", diff_source("garbage"))[0].status == 400
    assert app._slots.acquire(blocking=False)


def test_cross_origin_posts_are_refused():
    app = make_app()
    ok, _ = post(app, "/api/analyze", {}, headers={"origin": "https://changerisk.example"})
    assert ok.status == 400  # same origin gets through to validation
    for origin in ("https://evil.example", "https://changerisk.example.evil.net"):
        res, _ = post(app, "/api/analyze", {}, headers={"origin": origin})
        assert res.status == 403
    assert post(app, "/api/analyze", {}, headers={"sec-fetch-site": "cross-site"})[0].status == 403
    allowed = make_app(settings={"allowed_origins": ("https://partner.example",)})
    assert (
        post(allowed, "/api/analyze", {}, headers={"origin": "https://partner.example"})[0].status
        == 400
    )


def test_frame_ancestors_are_only_opened_for_named_embedders():
    plain = make_app().security_headers()
    assert (
        "frame-ancestors 'none'" in plain["Content-Security-Policy"]
        and plain["X-Frame-Options"] == "DENY"
    )
    framed = make_app(
        settings={"frame_ancestors": ("https://huggingface.co", "https://*.huggingface.co")}
    ).security_headers()
    assert (
        "frame-ancestors 'self' https://huggingface.co https://*.huggingface.co"
        in framed["Content-Security-Policy"]
    )
    assert (
        "X-Frame-Options" not in framed and "script-src 'self'" in framed["Content-Security-Policy"]
    )


def test_static_files_and_traversal():
    app = make_app()
    assert app.handle("GET", "/", {"host": "x"}).status == 200
    assert (
        app.handle("GET", "/js/main.js", {"host": "x"})
        .headers["Content-Type"]
        .startswith("text/javascript")
    )
    for path in ("/../pyproject.toml", "/%2e%2e/pyproject.toml", "/.git/config", "/js"):
        assert app.handle("GET", path, {"host": "x"}).status == 404


# --- exports ------------------------------------------------------------------------------------------


def test_render_any_format_from_a_report_the_client_holds(diff_text):
    app = make_app()
    _, report = post(app, "/api/analyze", diff_source(diff_text))
    expected = {
        "json": "application/json",
        "markdown": "text/markdown",
        "sarif": "application/sarif+json",
        "text": "text/plain",
        "html": "text/html",
    }
    for fmt, ctype in expected.items():
        res, body = post(app, "/api/render", {"format": fmt, "report": report})
        assert res.status == 200 and res.headers["Content-Type"].startswith(ctype), fmt
        assert res.headers["Content-Disposition"].startswith(
            'attachment; filename="changerisk-report.'
        )
    _, md = post(app, "/api/render", {"format": "markdown", "report": report})
    assert md.startswith("<!-- changerisk-report -->")


def test_render_rejects_garbage():
    app = make_app()
    assert post(app, "/api/render", {"format": "pdf", "report": {}})[0].status == 400
    for bad in ({}, {"score": 1}, "text", None, {"findings": [1, 2]}):
        res, data = post(app, "/api/render", {"format": "json", "report": bad})
        assert res.status == 400 and "does not look like" in data["error"]


def test_render_is_rate_limited_too():
    app = HostedApp(HostedSettings(rate_limit=1, rate_window=600))
    codes = [post(app, "/api/render", {"format": "pdf"})[0].status for _ in range(8)]
    assert codes[-1] in (400, 429)
    app._renders = RateLimiter(1, 600)
    post(app, "/api/render", {"format": "json", "report": {}})
    assert post(app, "/api/render", {"format": "json", "report": {}})[0].status == 429


# --- settings and helpers --------------------------------------------------------------------------------


def test_settings_from_environment():
    s = HostedSettings.from_env(
        {
            "GITHUB_TOKEN": "t",
            "CHANGERISK_RATE_LIMIT": "5",
            "CHANGERISK_TRUSTED_PROXIES": "2",
            "CHANGERISK_FRAME_ANCESTORS": "https://a.example, https://b.example",
            "CHANGERISK_MAX_CONCURRENT": "x",
        }
    )
    assert (s.github_token, s.rate_limit, s.trusted_proxies, s.max_concurrent) == ("t", 5, 2, 4)
    assert s.frame_ancestors == ("https://a.example", "https://b.example")
    assert HostedSettings.from_env({}).github_token is None


def test_ttl_cache_expiry_and_size():
    clock = Clock()
    cache = TTLCache(10, size=2, clock=clock)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None and cache.get("b") == 2
    clock.now += 11
    assert cache.get("b") is None


# --- over a real socket -------------------------------------------------------------------------------------


@pytest.mark.slow
def test_live_server_limits_and_round_trip(diff_text):
    httpd, _ = hosted.create_hosted_server("127.0.0.1", 0, HostedSettings(rate_limit=100))
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("GET", "/")
        res = conn.getresponse()
        res.read()
        assert res.status == 200 and "frame-ancestors 'none'" in res.getheader(
            "Content-Security-Policy"
        )

        body = json.dumps(diff_source(diff_text))
        conn.request("POST", "/api/analyze", body, {"Content-Type": "application/json"})
        res = conn.getresponse()
        data = json.loads(res.read())
        assert res.status == 200 and data["level"] == "critical"

        # Declare an oversized body without sending it: the server must refuse from the header alone.
        conn.putrequest("POST", "/api/analyze")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Content-Length", str(HostedApp.max_body + 10))
        conn.endheaders()
        res = conn.getresponse()
        res.read()
        assert res.status == 413
    finally:
        conn.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
