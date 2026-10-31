"""The hosted dashboard: the same interface, for a server that has no repository.

The change comes from a pasted diff or a public GitHub pull request. The server keeps nothing:
no repository, no stored reports, no logs of what was submitted. Reports live in the visitor's
browser. Because it is public, it also does what a localhost tool never has to: rate-limits by
client, caps the size and cost of one request, only talks to GitHub, and refuses to be framed
by sites it does not know.
"""

from __future__ import annotations

import ipaddress
import json
import os
import sys
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from http.server import ThreadingHTTPServer
from typing import Any

from . import __version__
from .config import Config
from .engine import analyze_changes
from .models import Level, RiskReport
from .remote import MAX_DIFF_BYTES, GitHub, SourceError, load_source
from .reports import render
from .rules import load_all
from .rules.base import describe_rules
from .server import (
    CSP,
    EXPORTS,
    SECURITY_HEADERS,
    Response,
    WebApp,
    make_handler,
)

GATES = ("never", "moderate", "high", "critical")


@dataclass
class HostedSettings:
    github_token: str | None = None
    rate_limit: int = 20  # analyses per window, per client
    rate_window: int = 600  # seconds
    max_concurrent: int = 4
    cache_seconds: int = 300
    analysis_seconds: float = 25.0
    trusted_proxies: int = 0  # reverse proxies in front of us, for reading X-Forwarded-For
    allowed_origins: tuple[str, ...] = ()
    frame_ancestors: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> HostedSettings:
        def num(name: str, default: int) -> int:
            try:
                return max(1, int(env.get(name, default)))
            except ValueError:
                return default

        def listing(name: str) -> tuple[str, ...]:
            return tuple(x.strip() for x in env.get(name, "").split(",") if x.strip())

        return cls(
            github_token=env.get("GITHUB_TOKEN") or None,
            rate_limit=num("CHANGERISK_RATE_LIMIT", 20),
            rate_window=num("CHANGERISK_RATE_WINDOW", 600),
            max_concurrent=num("CHANGERISK_MAX_CONCURRENT", 4),
            cache_seconds=num("CHANGERISK_CACHE_SECONDS", 300),
            trusted_proxies=max(0, int(env.get("CHANGERISK_TRUSTED_PROXIES", "0") or 0)),
            allowed_origins=listing("CHANGERISK_ALLOWED_ORIGINS"),
            frame_ancestors=listing("CHANGERISK_FRAME_ANCESTORS"),
        )


class RateLimiter:
    """At most `limit` requests per `window` seconds for each key (a sliding window)."""

    MAX_KEYS = 20000

    def __init__(
        self, limit: int, window: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.limit, self.window, self._clock = limit, window, clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> tuple[bool, int]:
        """Record a hit. Returns (allowed, seconds until the next hit would be allowed)."""
        now = self._clock()
        with self._lock:
            if len(self._hits) > self.MAX_KEYS:
                self._hits = {
                    k: v for k, v in self._hits.items() if v and now - v[-1] < self.window
                }
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False, max(1, int(self.window - (now - hits[0])) + 1)
            hits.append(now)
            return True, 0


class TTLCache:
    def __init__(
        self, ttl: int, size: int = 64, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.ttl, self.size, self._clock = ttl, size, clock
        self._items: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._items.get(key)
            if entry is None:
                return None
            if self._clock() - entry[0] > self.ttl:
                del self._items[key]
                return None
            self._items.move_to_end(key)
            return entry[1]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            self._items[key] = (self._clock(), value)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)


class HostedApp(WebApp):
    read_timeout = 30.0
    # Room for a diff at the size limit once it is wrapped in JSON and escaped.
    max_body = int(MAX_DIFF_BYTES * 1.3) + 16 * 1024

    def __init__(
        self,
        settings: HostedSettings | None = None,
        github: Callable[[], GitHub] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__()
        load_all()
        self.settings = settings or HostedSettings()
        self._github = github or (lambda: GitHub(self.settings.github_token))
        self._analyses = RateLimiter(self.settings.rate_limit, self.settings.rate_window, clock)
        self._renders = RateLimiter(self.settings.rate_limit * 6, self.settings.rate_window, clock)
        self._slots = threading.BoundedSemaphore(self.settings.max_concurrent)
        self._cache = TTLCache(self.settings.cache_seconds, clock=clock)
        self._chain_samples = 3  # how many requests still get their proxy chain length logged

    # -- request checks -------------------------------------------------------

    def security_headers(self) -> dict[str, str]:
        headers = dict(SECURITY_HEADERS)
        if self.settings.frame_ancestors:
            # A named list of embedders (for example the Hugging Face page that frames a Space).
            ancestors = "'self' " + " ".join(self.settings.frame_ancestors)
            headers["Content-Security-Policy"] = CSP.replace(
                "frame-ancestors 'none'", f"frame-ancestors {ancestors}"
            )
            del headers["X-Frame-Options"]  # it cannot express an allow-list
        return headers

    def check_request(self, method: str, headers: dict[str, str]) -> Response | None:
        if method not in ("GET", "HEAD", "POST", "OPTIONS"):
            return Response.error(405, "method not allowed")
        if method == "POST":
            origin = headers.get("origin")
            host = headers.get("host", "")
            same_site = (f"https://{host}", f"http://{host}")
            if origin and origin not in self.settings.allowed_origins and origin not in same_site:
                return Response.error(403, "cross-origin request refused")
            if headers.get("sec-fetch-site") not in (None, "same-origin", "none") and not origin:
                return Response.error(403, "cross-site request refused")
        return None

    def client_key(self, headers: dict[str, str], peer: str) -> str:
        """The address to rate-limit. Behind a reverse proxy the proxy's own address is useless."""
        hops = self.settings.trusted_proxies
        forwarded = [p.strip() for p in headers.get("x-forwarded-for", "").split(",") if p.strip()]
        if hops and self._chain_samples > 0:
            # Only a count, never an address: enough to check CHANGERISK_TRUSTED_PROXIES is right.
            self._chain_samples -= 1
            print(
                f"proxy check: X-Forwarded-For has {len(forwarded)} entries, trusting {hops}",
                file=sys.stderr,
                flush=True,
            )
        if hops and forwarded:
            candidate = forwarded[max(0, len(forwarded) - hops)]
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                pass
        return peer or "unknown"

    # -- routing --------------------------------------------------------------

    def api(
        self,
        method: str,
        path: str,
        target: str,
        headers: dict[str, str],
        body: bytes,
        peer: str,
    ) -> Response:
        if method == "OPTIONS":
            return Response(204)
        if path == "/api/health" and method == "GET":
            return Response.json({"ok": True, "version": __version__, "hosted": True})
        if path == "/api/repo" and method == "GET":
            return Response.json(self.info())
        if path == "/api/rules" and method == "GET":
            return Response.json({"rules": describe_rules(Config())})
        if path in ("/api/analyze", "/api/render"):
            if method != "POST":
                return Response.error(405, "use POST")
            payload = self._payload(headers, body)
            if isinstance(payload, Response):
                return payload
            key = self.client_key(headers, peer)
            if path == "/api/analyze":
                return self.analyze(payload, key)
            return self.render_report(payload, key)
        return Response.error(404, "no such endpoint")

    def info(self) -> dict[str, Any]:
        return {
            "hosted": True,
            "name": "ChangeRisk",
            "version": __version__,
            "limits": {
                "max_diff_kb": MAX_DIFF_BYTES // 1024,
                "analyses": self.settings.rate_limit,
                "window_minutes": max(1, self.settings.rate_window // 60),
            },
            "github_token": bool(self.settings.github_token),
        }

    @staticmethod
    def _payload(headers: dict[str, str], body: bytes) -> dict[str, Any] | Response:
        if not headers.get("content-type", "").startswith("application/json"):
            return Response.error(415, "send JSON with Content-Type: application/json")
        try:
            payload = json.loads(body or b"{}")
        except ValueError:
            return Response.error(400, "the request body is not valid JSON")
        if not isinstance(payload, dict):
            return Response.error(400, "the request body must be a JSON object")
        return payload

    # -- endpoints ------------------------------------------------------------

    def analyze(self, payload: dict[str, Any], key: str) -> Response:
        source = payload.get("source")
        if not isinstance(source, dict):
            return Response.error(400, "send a source: a pasted diff or a GitHub pull request URL")
        fail_on = payload.get("fail_on", "high")
        if fail_on not in GATES:
            return Response.error(400, f"fail_on must be one of: {', '.join(GATES)}")

        allowed, retry = self._analyses.check(key)
        if not allowed:
            res = Response.error(
                429,
                f"Slow down: this server allows {self.settings.rate_limit} analyses every "
                f"{max(1, self.settings.rate_window // 60)} minutes per visitor. Try again in "
                f"{retry} seconds, or run ChangeRisk locally.",
            )
            res.headers["Retry-After"] = str(retry)
            return res
        if not self._slots.acquire(blocking=False):
            res = Response.error(
                503, "The server is busy with other analyses. Try again in a few seconds."
            )
            res.headers["Retry-After"] = "5"
            return res
        try:
            cache_key = self._cache_key(source, fail_on)
            if cache_key and (hit := self._cache.get(cache_key)) is not None:
                return Response.json(hit)
            deadline = time.monotonic() + self.settings.analysis_seconds
            changes, config, notes = load_source(self._github(), source)
            config.fail_on = None if fail_on == "never" else Level.parse(fail_on)
            report = analyze_changes(
                changes, config, None, include_diffs="flagged", notes=notes, deadline=deadline
            )
            data = report.to_dict()
            if cache_key:
                self._cache.put(cache_key, data)
            return Response.json(data)
        except SourceError as exc:
            return Response.error(exc.status, str(exc))
        finally:
            self._slots.release()

    @staticmethod
    def _cache_key(source: dict[str, Any], fail_on: str) -> str | None:
        """Only public GitHub data is cached; a pasted diff is never kept."""
        if source.get("type") != "github" or not isinstance(source.get("url"), str):
            return None
        return f"{source['url'].strip().lower()}|{fail_on}"

    def render_report(self, payload: dict[str, Any], key: str) -> Response:
        fmt = payload.get("format")
        if fmt not in EXPORTS:
            return Response.error(400, f"format must be one of: {', '.join(EXPORTS)}")
        allowed, retry = self._renders.check(key)
        if not allowed:
            res = Response.error(429, f"Too many exports. Try again in {retry} seconds.")
            res.headers["Retry-After"] = str(retry)
            return res
        try:
            report = RiskReport.from_dict(payload.get("report") or {})
            text = render(report, fmt)
        except (KeyError, TypeError, ValueError, AttributeError):
            return Response.error(400, "that does not look like a ChangeRisk report")
        ctype, ext = EXPORTS[fmt]
        return Response(
            200,
            text.encode("utf-8"),
            {
                "Content-Type": f"{ctype}; charset=utf-8",
                "Content-Disposition": f'attachment; filename="changerisk-report.{ext}"',
                "Cache-Control": "no-store",
            },
        )


def create_hosted_server(
    host: str = "0.0.0.0",
    port: int = 7860,
    settings: HostedSettings | None = None,
    github: Callable[[], GitHub] | None = None,
) -> tuple[ThreadingHTTPServer, HostedApp]:
    app = HostedApp(settings or HostedSettings.from_env(), github)
    server = ThreadingHTTPServer((host, port), make_handler(app))
    server.daemon_threads = True
    return server, app


def serve_hosted(host: str, port: int) -> int:
    server, app = create_hosted_server(host, port)
    s = app.settings
    print(
        f"ChangeRisk (hosted) listening on {host}:{server.server_address[1]}\n"
        f"  GitHub token: {'set' if s.github_token else 'not set (anonymous API limit applies)'}\n"
        f"  per-visitor limit: {s.rate_limit} analyses / {s.rate_window}s, "
        f"{s.max_concurrent} at a time, trusted proxies: {s.trusted_proxies}",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped", file=sys.stderr)
    finally:
        server.server_close()
    return 0
