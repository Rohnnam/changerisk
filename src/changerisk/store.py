"""Saved reports, kept as JSON files under `.changerisk/` inside the repository."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import RiskReport

KEEP = 200
ID_PATTERN = re.compile(r"^[0-9A-Za-z][0-9A-Za-z_.-]{3,80}$")


def summarize(data: dict[str, Any]) -> dict[str, Any]:
    rng = data.get("range", {})
    stats = data.get("stats", {})
    return {
        "id": data.get("id"),
        "generated_at": data.get("generated_at"),
        "repo": data.get("repo"),
        "mode": rng.get("mode"),
        "base": rng.get("base"),
        "head": rng.get("head"),
        "head_sha": (rng.get("head_sha") or "")[:8],
        "score": data.get("score"),
        "level": data.get("level"),
        "gate_failed": data.get("gate", {}).get("failed"),
        "files": stats.get("files"),
        "additions": stats.get("additions"),
        "deletions": stats.get("deletions"),
        "findings": len(data.get("findings", [])),
        "top": [f["title"] for f in data.get("findings", [])[:3]],
    }


class ReportStore:
    def __init__(self, repo_root: Path) -> None:
        self.dir = Path(repo_root) / ".changerisk" / "reports"
        self._lock = threading.Lock()

    def _ensure(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        marker = self.dir.parent / ".gitignore"
        if not marker.exists():
            marker.write_text("*\n", encoding="utf-8")  # keeps the store out of commits

    def _new_id(self, stamp: datetime, report: RiskReport) -> str:
        tail = (report.head_sha or report.mode)[:7]
        base = f"{stamp.strftime('%Y%m%d-%H%M%S')}-{tail}"
        candidate, n = base, 1
        while (self.dir / f"{candidate}.json").exists():
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def save(self, report: RiskReport, created: datetime | None = None) -> str:
        with self._lock:
            self._ensure()
            stamp = (created or datetime.now(UTC)).astimezone(UTC)
            report.generated_at = stamp.isoformat(timespec="seconds")
            report.id = self._new_id(stamp, report)
            target = self.dir / f"{report.id}.json"
            tmp = target.with_suffix(".tmp")
            tmp.write_text(json.dumps(report.to_dict(), ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, target)
            self._prune()
            return report.id

    def _files(self) -> list[Path]:
        if not self.dir.is_dir():
            return []
        return sorted(self.dir.glob("*.json"), reverse=True)

    def _prune(self) -> None:
        for old in self._files()[KEEP:]:
            old.unlink(missing_ok=True)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        out = []
        for path in self._files()[:limit]:
            try:
                out.append(summarize(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue  # a half-written or hand-edited file should not break the list
        out.sort(key=lambda s: s.get("generated_at") or "", reverse=True)
        return out

    def get(self, report_id: str) -> dict[str, Any] | None:
        if not ID_PATTERN.match(report_id):
            return None
        path = self.dir / f"{report_id}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, report_id: str) -> bool:
        if not ID_PATTERN.match(report_id):
            return False
        path = self.dir / f"{report_id}.json"
        try:
            path.unlink()
        except OSError:
            return False
        return True
