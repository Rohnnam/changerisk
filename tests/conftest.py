"""Shared fixtures. Tests run against real git repositories built in temp directories."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from changerisk.paths import Classifier

CLOCK_START = datetime(2026, 3, 1, tzinfo=UTC)


class Repo:
    """A throwaway git repository with helpers for building history."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._tick = 0
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test Author")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args: str, check: bool = True) -> str:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        proc = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, env=env, check=False
        )
        out = proc.stdout.decode("utf-8", errors="replace")
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {proc.stderr.decode()}")
        return out

    def write(self, path: str, content: str | bytes) -> Path:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_bytes(content.replace("\r\n", "\n").encode("utf-8"))
        return target

    def remove(self, path: str) -> None:
        (self.root / path).unlink()

    def commit(self, message: str, *, author: str = "Test Author", when: str | None = None) -> str:
        """Stage everything and commit, with a clock that moves forward one hour per commit."""
        self._tick += 1
        stamp = when or (CLOCK_START + timedelta(hours=self._tick)).isoformat()
        env = dict(
            os.environ,
            GIT_AUTHOR_NAME=author,
            GIT_AUTHOR_EMAIL=f"{author.split()[0].lower()}@example.com",
            GIT_COMMITTER_NAME=author,
            GIT_COMMITTER_EMAIL=f"{author.split()[0].lower()}@example.com",
            GIT_AUTHOR_DATE=stamp,
            GIT_COMMITTER_DATE=stamp,
        )
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True, env=env)
        subprocess.run(
            ["git", "commit", "-q", "--allow-empty", "-m", message],
            cwd=self.root, check=True, capture_output=True, env=env,
        )  # fmt: skip
        return self.git("rev-parse", "HEAD").strip()

    def branch(self, name: str, start: str | None = None) -> None:
        self.git("checkout", "-q", "-b", name, *([start] if start else []))

    def checkout(self, ref: str) -> None:
        self.git("checkout", "-q", ref)


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[str], Repo]:
    count = 0

    def factory(name: str = "repo") -> Repo:
        nonlocal count
        count += 1
        root = tmp_path / f"{name}{count}"
        root.mkdir()
        return Repo(root)

    return factory


@pytest.fixture
def repo(make_repo: Callable[[str], Repo]) -> Repo:
    return make_repo("repo")


@pytest.fixture
def classifier() -> Classifier:
    return Classifier()
