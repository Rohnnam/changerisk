"""The local dashboard: a JSON API plus the static frontend, on the standard library only."""

from __future__ import annotations

import json
import mimetypes
import re
import sys
import threading
import traceback
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from . import __version__, gitops
from .config import ConfigError, find_config, load_config
from .engine import analyze
from .gitops import GitError
from .models import RiskReport
from .reports import render
from .rules import load_all
from .rules.base import describe_rules, option_defaults
from .store import ReportStore
from .webassets import web_dir

EXPORTS = {
    "html": ("text/html", "html"),
    "json": ("application/json", "json"),
    "markdown": ("text/markdown", "md"),
    "sarif": ("application/sarif+json", "sarif"),
    "text": ("text/plain", "txt"),
}
MAX_BODY = 64 * 1024
LOOPBACK = {"127.0.0.1", "localhost", "[::1]"}
STATIC_TYPES = {".html", ".css", ".js", ".mjs", ".svg", ".png", ".ico", ".json", ".woff2", ".txt"}
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
}
_BRANCH_FORMAT = (
    "%(refname)%09%(refname:short)%09%(objectname:short)%09%(committerdate:iso-strict)%09%(subject)"
)
_KINDS = (("refs/heads/", "branch"), ("refs/remotes/", "remote"), ("refs/tags/", "tag"))

mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)

    @staticmethod
    def json(data, status: int = 200) -> Response:
        return Response(
            status, json.dumps(data, ensure_ascii=False).encode("utf-8"),
            {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        )  # fmt: skip

    @staticmethod
    def error(status: int, message: str) -> Response:
        return Response.json({"error": message}, status)


class WebApp:
    """Routing, static files and request checks, without any sockets so it can be tested directly.

    Subclasses decide what the API does and which requests are acceptable.
    """

    max_body = MAX_BODY
    read_timeout: float | None = None  # seconds a client may stall; None means no limit

    def __init__(self) -> None:
        self.web = web_dir()

    def security_headers(self) -> dict[str, str]:
        return dict(SECURITY_HEADERS)

    def check_request(self, method: str, headers: dict[str, str]) -> Response | None:
        raise NotImplementedError

    def api(
        self,
        method: str,
        path: str,
        target: str,
        headers: dict[str, str],
        body: bytes,
        peer: str,
    ) -> Response:
        raise NotImplementedError

    def handle(
        self,
        method: str,
        target: str,
        headers: dict[str, str],
        body: bytes = b"",
        peer: str = "",
    ) -> Response:
        headers = {k.lower(): v for k, v in headers.items()}
        denied = self.check_request(method, headers)
        if denied:
            return denied
        path = unquote(urlsplit(target).path)
        try:
            if path.startswith("/api/"):
                return self.api(method, path, target, headers, body, peer)
            if method not in ("GET", "HEAD"):
                return Response.error(405, "method not allowed")
            return self._static(path)
        except GitError as exc:
            return Response.error(422, str(exc))
        except ConfigError as exc:
            return Response.error(422, str(exc))

    # -- static files ---------------------------------------------------------

    def _static(self, path: str) -> Response:
        rel = "index.html" if path in ("", "/") else path.lstrip("/")
        parts = Path(rel).parts
        if ".." in parts or Path(rel).is_absolute() or any(p.startswith(".") for p in parts):
            return Response.error(404, "not found")
        target = (self.web / rel).resolve()
        try:
            target.relative_to(self.web.resolve())
        except ValueError:
            return Response.error(404, "not found")
        if not target.is_file() or target.suffix.lower() not in STATIC_TYPES:
            return Response.error(404, "not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("json"):
            ctype += "; charset=utf-8"
        return Response(
            200, target.read_bytes(), {"Content-Type": ctype, "Cache-Control": "no-cache"}
        )


class App(WebApp):
    """The local dashboard: one repository on this machine, reports kept in `.changerisk/`."""

    def __init__(self, repo: Path | str, port: int = 0, host: str = "127.0.0.1") -> None:
        super().__init__()
        load_all()
        self.root = gitops.repo_root(repo)
        self.store = ReportStore(self.root)
        self.allowed_hosts: set[str] = set()
        self.bind(host, port)
        self._analysis = threading.Lock()

    def bind(self, host: str, port: int) -> None:
        """Record which Host headers are legitimate for the address we ended up listening on."""
        self.allowed_hosts = {f"{name}:{port}" for name in LOOPBACK | {host}}

    def check_request(self, method: str, headers: dict[str, str]) -> Response | None:
        host = headers.get("host", "")
        if host not in self.allowed_hosts:
            return Response.error(403, "unexpected Host header")
        if method in ("POST", "DELETE", "PUT", "PATCH"):
            origin = headers.get("origin")
            if origin and origin not in (f"http://{host}", f"https://{host}"):
                return Response.error(403, "cross-origin request refused")
            if headers.get("sec-fetch-site") not in (None, "same-origin", "none"):
                return Response.error(403, "cross-site request refused")
        return None

    def api(
        self,
        method: str,
        path: str,
        target: str,
        headers: dict[str, str],
        body: bytes,
        peer: str,
    ) -> Response:
        if path == "/api/health" and method == "GET":
            return Response.json({"ok": True, "version": __version__})
        if path == "/api/repo" and method == "GET":
            return Response.json(self.repo_info())
        if path == "/api/rules" and method == "GET":
            return Response.json({"rules": self.rules_info()})
        if path == "/api/reports" and method == "GET":
            return Response.json({"reports": self.store.list()})
        if path == "/api/analyze":
            if method != "POST":
                return Response.error(405, "use POST")
            return self.run_analysis(headers, body)
        m = re.fullmatch(r"/api/reports/([^/]+)/export", path)
        if m and method == "GET":
            return self.export(m.group(1), urlsplit(target).query)
        m = re.fullmatch(r"/api/reports/([^/]+)", path)
        if m:
            if method == "GET":
                data = self.store.get(m.group(1))
                return Response.json(data) if data else Response.error(404, "no such report")
            if method == "DELETE":
                ok = self.store.delete(m.group(1))
                return (
                    Response.json({"deleted": True})
                    if ok
                    else Response.error(404, "no such report")
                )
            return Response.error(405, "method not allowed")
        return Response.error(404, "no such endpoint")

    # -- endpoints ------------------------------------------------------------

    def repo_info(self) -> dict:
        root = self.root
        refs = []
        listing = gitops.run_git(
            root, "for-each-ref", "--sort=-committerdate", "--count=120",
            f"--format={_BRANCH_FORMAT}", "refs/heads", "refs/remotes", "refs/tags", check=False,
        )  # fmt: skip
        for line in listing.splitlines():
            full, name, sha, date, subject = (line.split("\t") + ["", "", "", "", ""])[:5]
            kind = next((k for prefix, k in _KINDS if full.startswith(prefix)), None)
            if not name or kind is None or name.endswith("/HEAD"):
                continue
            refs.append({"name": name, "kind": kind, "sha": sha, "date": date, "subject": subject})
        commits = []
        if gitops.has_commits(root):
            log = gitops.run_git(
                root,
                "log",
                "--no-color",
                "-n",
                "30",
                "--format=%h%x09%an%x09%aI%x09%s",
                check=False,
            )
            for line in log.splitlines():
                sha, author, date, subject = (line.split("\t") + ["", "", ""])[:4]
                commits.append({"sha": sha, "author": author, "date": date, "subject": subject})
        cfg_path = find_config(root)
        return {
            "name": gitops.repo_name(root),
            "path": str(root),
            "branch": gitops.current_branch(root),
            "default_base": gitops.default_base(root),
            "shallow": gitops.is_shallow(root),
            "has_commits": gitops.has_commits(root),
            "refs": refs,
            "commits": commits,
            "config": str(cfg_path.relative_to(root)) if cfg_path else None,
            "version": __version__,
        }

    def rules_info(self) -> list[dict]:
        return describe_rules(load_config(self.root, rule_options=option_defaults()))

    def export(self, report_id: str, query: str) -> Response:
        fmt = (parse_qs(query).get("format") or ["json"])[0]
        if fmt not in EXPORTS:
            return Response.error(400, f"format must be one of: {', '.join(EXPORTS)}")
        data = self.store.get(report_id)
        if data is None:
            return Response.error(404, "no such report")
        text = render(RiskReport.from_dict(data), fmt)
        ctype, ext = EXPORTS[fmt]
        return Response(
            200, text.encode("utf-8"),
            {
                "Content-Type": f"{ctype}; charset=utf-8",
                "Content-Disposition": f'attachment; filename="changerisk-{report_id}.{ext}"',
                "Cache-Control": "no-store",
            },
        )  # fmt: skip

    def run_analysis(self, headers: dict[str, str], body: bytes) -> Response:
        if not headers.get("content-type", "").startswith("application/json"):
            return Response.error(415, "send JSON with Content-Type: application/json")
        if len(body) > MAX_BODY:
            return Response.error(413, "request body too large")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return Response.error(400, "body is not valid JSON")
        if not isinstance(payload, dict):
            return Response.error(400, "body must be a JSON object")

        mode = payload.get("mode", "range")
        if mode not in ("range", "staged", "worktree"):
            return Response.error(400, "mode must be range, staged or worktree")
        base, head = payload.get("base") or None, payload.get("head") or None
        for name, value in (("base", base), ("head", head)):
            if value is not None:
                if not isinstance(value, str):
                    return Response.error(400, f"{name} must be a string")
                try:
                    gitops.validate_ref(value)
                except GitError as exc:
                    return Response.error(400, str(exc))
        use_history = payload.get("history")
        if use_history is not None and not isinstance(use_history, bool):
            return Response.error(400, "history must be true or false")

        with self._analysis:
            report = analyze(
                self.root, base=base, head=head, mode=mode, use_history=use_history,
                include_diffs="flagged",
            )  # fmt: skip
            self.store.save(report)
        return Response.json(report.to_dict())


def make_handler(app: WebApp) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "changerisk"
        sys_version = ""
        timeout = app.read_timeout

        def _serve(self) -> None:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = -1
            if length < 0 or length > app.max_body:
                self._send(
                    Response.error(413 if length > 0 else 400, "bad or oversized request body")
                )
                self.close_connection = True
                return
            body = self.rfile.read(length) if length else b""
            try:
                res = app.handle(
                    self.command,
                    self.path,
                    dict(self.headers.items()),
                    body,
                    self.client_address[0],
                )
            except Exception:  # keep the connection answerable whatever went wrong
                traceback.print_exc()
                res = Response.error(500, "internal error; see the server log")
            self._send(res)

        def _send(self, res: Response) -> None:
            self.send_response(res.status)
            for k, v in {**app.security_headers(), **res.headers}.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(res.body)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(res.body)

        do_GET = do_POST = do_DELETE = do_HEAD = do_PUT = do_PATCH = _serve

        def log_message(self, fmt: str, *args) -> None:
            sys.stderr.write(f"  {fmt % args}\n")

    return Handler


def create_server(
    repo: Path | str, host: str = "127.0.0.1", port: int = 8765
) -> tuple[ThreadingHTTPServer, App]:
    probe = App(repo, port=port, host=host)  # validates the repo before binding anything
    server = ThreadingHTTPServer((host, port), make_handler(probe))
    server.daemon_threads = True
    probe.bind(host, server.server_address[1])
    return server, probe


def serve(repo: Path | str, host: str, port: int, *, open_browser: bool = True) -> int:
    server, app = create_server(repo, host, port)
    url = (
        f"http://{host if host not in ('0.0.0.0', '') else '127.0.0.1'}:{server.server_address[1]}/"
    )
    if host not in LOOPBACK:
        print(
            "warning: listening beyond localhost. There is no login; anyone who can reach this "
            "port can run analyses on this repository.", file=sys.stderr,
        )  # fmt: skip
    print(f"ChangeRisk dashboard for {app.root}\n  {url}\n  Ctrl+C to stop")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
    return 0
