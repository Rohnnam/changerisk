import http.client
import json
import threading

import pytest

from changerisk import server
from changerisk.store import ReportStore

from .test_engine import risky_branch, seeded


@pytest.fixture
def web(tmp_path, monkeypatch):
    d = tmp_path / "web"
    (d / "js").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><title>t</title>", encoding="utf-8")
    (d / "js" / "app.js").write_text("export const x = 1;\n", encoding="utf-8")
    (d / "notes.exe").write_text("nope", encoding="utf-8")
    (d / ".secret.txt").write_text("hidden", encoding="utf-8")
    (tmp_path / "outside.txt").write_text("outside", encoding="utf-8")
    monkeypatch.setenv("CHANGERISK_WEB_DIR", str(d))
    return d


@pytest.fixture
def app(repo, web):
    seeded(repo)
    risky_branch(repo)
    a = server.App(repo.root, port=8765)
    return a


HOST = {"Host": "127.0.0.1:8765"}


def call(app, method, path, body=None, headers=None):
    h = dict(HOST, **(headers or {}))
    raw = b""
    if body is not None:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        h.setdefault("Content-Type", "application/json")
    res = app.handle(method, path, h, raw)
    data = (
        json.loads(res.body)
        if res.headers.get("Content-Type", "").startswith("application/json")
        else res.body
    )
    return res, data


# --- read endpoints ----------------------------------------------------------


def test_index_and_static_files(app):
    res, body = call(app, "GET", "/")
    assert res.status == 200 and res.headers["Content-Type"].startswith("text/html")
    res, _ = call(app, "GET", "/js/app.js")
    assert res.status == 200 and res.headers["Content-Type"].startswith("text/javascript")


def test_repo_info(app, repo):
    res, info = call(app, "GET", "/api/repo")
    assert res.status == 200
    assert info["branch"] == "feature/speedup" and info["default_base"] == "main"
    assert {r["name"] for r in info["refs"]} >= {"main", "feature/speedup"}
    assert info["commits"][0]["subject"] == "Speed up checkout"
    assert info["config"] is None and info["shallow"] is False


def test_rules_endpoint_reflects_config(app, repo):
    (repo.root / "changerisk.toml").write_text(
        '[rules]\ndisable = ["COD003"]\n[rules.SIZ001]\nseverity = "high"\n', encoding="utf-8"
    )
    _, data = call(app, "GET", "/api/rules")
    by_id = {r["id"]: r for r in data["rules"]}
    assert len(by_id) == 33
    assert by_id["COD003"]["enabled"] is False and by_id["SIZ001"]["severity"] == "high"
    assert by_id["SIZ001"]["options"]["medium_lines"] == 400


def test_health(app):
    assert call(app, "GET", "/api/health")[1]["ok"] is True


# --- analysis and the store ---------------------------------------------------


def test_analyze_saves_lists_fetches_and_deletes(app, repo):
    res, report = call(
        app, "POST", "/api/analyze", {"base": "main", "head": "feature/speedup", "history": False}
    )
    assert res.status == 200 and report["level"] == "critical" and report["id"]
    assert (repo.root / ".changerisk" / ".gitignore").read_text(encoding="utf-8") == "*\n"

    _, listing = call(app, "GET", "/api/reports")
    assert [r["id"] for r in listing["reports"]] == [report["id"]]
    assert listing["reports"][0]["findings"] == len(report["findings"])

    res, again = call(app, "GET", f"/api/reports/{report['id']}")
    assert res.status == 200 and again["score"] == report["score"]
    assert again["files"][0]["hunks"]  # diffs for flagged files are stored

    res, _ = call(app, "DELETE", f"/api/reports/{report['id']}")
    assert res.status == 200
    assert call(app, "GET", f"/api/reports/{report['id']}")[0].status == 404
    assert git_status_is_clean_of_store(repo)


def test_export_formats(app, monkeypatch):
    monkeypatch.delenv("CHANGERISK_WEB_DIR")  # the HTML export bundles the real frontend
    _, report = call(
        app, "POST", "/api/analyze", {"base": "main", "head": "feature/speedup", "history": False}
    )
    rid = report["id"]
    expected = {
        "json": ("application/json", "json"),
        "markdown": ("text/markdown", "md"),
        "sarif": ("application/sarif+json", "sarif"),
        "text": ("text/plain", "txt"),
        "html": ("text/html", "html"),
    }
    for fmt, (ctype, ext) in expected.items():
        res = app.handle("GET", f"/api/reports/{rid}/export?format={fmt}", dict(HOST), b"")
        assert res.status == 200, fmt
        assert res.headers["Content-Type"].startswith(ctype)
        assert (
            res.headers["Content-Disposition"] == f'attachment; filename="changerisk-{rid}.{ext}"'
        )
    md = app.handle(
        "GET", f"/api/reports/{rid}/export?format=markdown", dict(HOST), b""
    ).body.decode()
    assert md.startswith("<!-- changerisk-report -->")
    html = app.handle(
        "GET", f"/api/reports/{rid}/export?format=html", dict(HOST), b""
    ).body.decode()
    assert "window.__CHANGERISK__" in html


def test_export_rejects_bad_requests(app):
    _, report = call(
        app, "POST", "/api/analyze", {"base": "main", "head": "feature/speedup", "history": False}
    )
    rid = report["id"]
    assert call(app, "GET", f"/api/reports/{rid}/export?format=pdf")[0].status == 400
    assert (
        call(app, "GET", "/api/reports/20200101-000000-missing/export?format=json")[0].status == 404
    )
    assert call(app, "GET", "/api/reports/..%2F..%2Fx/export?format=json")[0].status == 404


def git_status_is_clean_of_store(repo):
    return ".changerisk" not in repo.git("status", "--porcelain")


def test_analyze_defaults_to_the_current_branch(app):
    res, report = call(app, "POST", "/api/analyze", {"history": False})
    assert res.status == 200 and report["range"]["base"] == "main"


def test_analyze_working_tree(app, repo):
    repo.write("config/production.yml", "debug: true\n")
    res, report = call(app, "POST", "/api/analyze", {"mode": "worktree", "history": False})
    assert res.status == 200 and report["range"]["mode"] == "worktree"


@pytest.mark.parametrize(
    ("payload", "status", "fragment"),
    [
        ({"base": "--upload-pack=x"}, 400, "not a usable git revision"),
        ({"base": "no-such-branch"}, 422, "unknown revision"),
        ({"mode": "everything"}, 400, "mode must be"),
        ({"base": 5}, 400, "must be a string"),
        ({"history": "yes"}, 400, "history must be"),
        ([1, 2], 400, "must be a JSON object"),
    ],
)
def test_analyze_validation(app, payload, status, fragment):
    res, data = call(app, "POST", "/api/analyze", payload)
    assert res.status == status and fragment in data["error"]


def test_analyze_needs_json_and_bounded_body(app):
    res, _ = call(app, "POST", "/api/analyze", b"{}", {"Content-Type": "text/plain"})
    assert res.status == 415
    res, _ = call(app, "POST", "/api/analyze", b"x" * (server.MAX_BODY + 1))
    assert res.status == 413
    res, _ = call(app, "POST", "/api/analyze", b"{not json")
    assert res.status == 400
    res, _ = call(app, "GET", "/api/analyze")
    assert res.status == 405


def test_report_ids_cannot_escape_the_store(app, tmp_path):
    for bad in ("..%2F..%2Fpyproject", "%2e%2e", "a", "x" * 200):
        assert call(app, "GET", f"/api/reports/{bad}")[0].status == 404
    assert call(app, "DELETE", "/api/reports/..")[0].status in (404, 405)


# --- hostile requests ----------------------------------------------------------


def test_unexpected_host_header_is_refused(app):
    res = app.handle("GET", "/api/repo", {"Host": "evil.example:8765"}, b"")
    assert res.status == 403
    assert app.handle("GET", "/", {}, b"").status == 403


def test_cross_origin_writes_are_refused(app):
    for origin in ("http://evil.example", "http://127.0.0.1:9999"):
        res, _ = call(app, "POST", "/api/analyze", {}, {"Origin": origin})
        assert res.status == 403
    res, _ = call(
        app, "POST", "/api/analyze", {"history": False}, {"Origin": "http://127.0.0.1:8765"}
    )
    assert res.status == 200
    res, _ = call(app, "POST", "/api/analyze", {}, {"Sec-Fetch-Site": "cross-site"})
    assert res.status == 403


@pytest.mark.parametrize(
    "path",
    [
        "/../outside.txt",
        "/%2e%2e/outside.txt",
        "/js/../../outside.txt",
        "/.secret.txt",
        "/notes.exe",
        "/nope.js",
        "//etc/passwd",
        "/js",
    ],
)
def test_static_paths_cannot_escape_or_leak(app, path):
    res, _ = call(app, "GET", path)
    assert res.status == 404


def test_unknown_methods_and_endpoints(app):
    assert call(app, "POST", "/index.html")[0].status == 405
    assert call(app, "GET", "/api/nothing")[0].status == 404


# --- real sockets --------------------------------------------------------------


@pytest.mark.slow
def test_live_server_headers_and_round_trip(repo, web):
    seeded(repo)
    risky_branch(repo)
    httpd, app = server.create_server(repo.root, "127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
    try:
        conn.request("GET", "/")
        res = conn.getresponse()
        res.read()
        assert res.status == 200
        assert "script-src 'self'" in res.getheader("Content-Security-Policy")
        assert res.getheader("X-Content-Type-Options") == "nosniff"
        assert res.getheader("X-Frame-Options") == "DENY"

        body = json.dumps({"base": "main", "head": "feature/speedup", "history": False})
        conn.request("POST", "/api/analyze", body, {"Content-Type": "application/json"})
        res = conn.getresponse()
        data = json.loads(res.read())
        assert res.status == 200 and data["score"] >= 75

        conn.request("GET", "/api/repo", headers={"Host": "attacker.example"})
        res = conn.getresponse()
        res.read()
        assert res.status == 403

        conn.request("HEAD", "/")
        res = conn.getresponse()
        assert res.status == 200 and res.read() == b""
    finally:
        conn.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
    assert ReportStore(repo.root).list()


def test_make_handler_rejects_non_numeric_content_length(repo, web):
    seeded(repo)
    httpd, _ = server.create_server(repo.root, "127.0.0.1", 0)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        conn.putrequest("POST", "/api/analyze")
        conn.putheader("Content-Length", "abc")
        conn.putheader("Content-Type", "application/json")
        conn.endheaders()
        res = conn.getresponse()
        res.read()
        assert res.status == 400
    finally:
        conn.close()
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
