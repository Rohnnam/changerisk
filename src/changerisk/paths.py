"""Path matching and the "what kind of file is this" questions the rules keep asking."""

from __future__ import annotations

import re
from collections.abc import Iterable
from functools import lru_cache
from pathlib import PurePosixPath


@lru_cache(maxsize=512)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate a gitignore-flavoured glob into a regex.

    `**` crosses directories, `*` and `?` do not. A pattern without a slash matches the
    file name at any depth, a trailing slash means "everything under this directory".
    """
    pat = pattern.strip().replace("\\", "/")
    anchored = pat.startswith("/")
    pat = pat.lstrip("/")
    if pat.endswith("/"):
        pat += "**"
    floating = "/" not in pat.rstrip("*") and not anchored

    out: list[str] = []
    i = 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if pat[i : i + 3] == "**/":
                out.append("(?:.*/)?")
                i += 3
                continue
            if pat[i : i + 2] == "**":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    body = "".join(out)
    prefix = r"(?:.*/)?" if floating else ""
    return re.compile(rf"^{prefix}{body}$", re.IGNORECASE)


def matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(compile_glob(p).match(path) for p in patterns)


# ---------------------------------------------------------------------------
# Built-in knowledge about file kinds
# ---------------------------------------------------------------------------

TEST_DIRS = {
    "test", "tests", "__tests__", "spec", "specs", "e2e", "integration_tests", "unit_tests",
    "cypress", "playwright",
}  # fmt: skip
TEST_NAME = re.compile(
    r"""(?ix)
    ^(?:test_.*\.py | .*_test\.(?:py|go|rb|rs|exs?) | conftest\.py
     | .*\.(?:test|spec)\.[cm]?[jt]sx? | .*_spec\.rb
     | .*Tests?\.(?:java|kt|cs|swift|scala) | .*IT\.java | .*Test\.php)$
    """
)

DOC_EXTS = {".md", ".mdx", ".rst", ".txt", ".adoc"}
DOC_NAMES = {"license", "licence", "notice", "authors", "contributors", "changelog", "codeowners"}

LOCKFILES = {
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb",
    "poetry.lock", "uv.lock", "pdm.lock", "pipfile.lock", "cargo.lock", "go.sum",
    "gemfile.lock", "composer.lock", "packages.lock.json", "gradle.lockfile",
}  # fmt: skip
GENERATED_DIRS = {
    "node_modules", "vendor", "dist", "build", ".next", "__generated__", "generated",
    "__snapshots__", "coverage", "target", "third_party",
}  # fmt: skip
GENERATED_NAME = re.compile(
    r"(?i)(?:\.min\.(?:js|css)|\.map|\.snap|_pb2(?:_grpc)?\.pyi?|\.pb\.go|\.generated\.\w+|\.designer\.cs)$"
)

LANGUAGES = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".java": "java", ".kt": "kotlin", ".scala": "scala", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".rs": "rust", ".swift": "swift",
    ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp", ".hpp": "cpp",
    ".sh": "shell", ".bash": "shell", ".ps1": "powershell",
    ".sql": "sql", ".tf": "terraform",
}  # fmt: skip
SOURCE_LANGS = set(LANGUAGES.values()) - {"shell", "powershell", "sql", "terraform"}

CONFIG_DIRS = {
    "config", "configs", "conf", "settings", "deploy", "deployment", "k8s", "kubernetes",
    "helm", "charts", "infra", "infrastructure", "environments", "envs", "terraform", "ansible",
}  # fmt: skip
CONFIG_NAME = re.compile(
    r"""(?ix)
    ^(?: \.env(?:\..+)?
       | settings(?:_\w+)?\.py | config(?:uration)?\.(?:py|js|ts|json|ya?ml|toml|rb)
       | application(?:-[\w.]+)?\.(?:ya?ml|properties) | appsettings(?:\.[\w]+)?\.json
       | docker-compose(?:\.[\w-]+)?\.ya?ml | compose(?:\.[\w-]+)?\.ya?ml | dockerfile(?:\.[\w.-]+)?
       | .*\.(?:tf|tfvars|ini|cfg|conf|properties)
       | nginx.*\.conf | procfile | \.npmrc | \.pypirc | pytest\.ini | tox\.ini | \.coveragerc
       | values(?:[-.][\w.-]+)?\.ya?ml | .*\.config\.[cm]?[jt]s )$
    """
)
ENV_TEMPLATE = re.compile(r"(?i)\.(?:example|sample|template|dist|defaults?)$")

PIPELINE_PATTERNS = (
    ".github/workflows/*.yml", ".github/workflows/*.yaml", ".github/actions/**",
    ".gitlab-ci.yml", ".gitlab/**/*.yml", "Jenkinsfile*", "azure-pipelines*.yml",
    ".circleci/**", ".travis.yml", "bitbucket-pipelines.yml", ".drone.yml", "cloudbuild.yaml",
)  # fmt: skip

MIGRATION_DIR = re.compile(
    r"(?i)(?:^|/)(?:migrations?|alembic/versions|db/migrate|flyway|liquibase|prisma/migrations)/"
)

MANIFESTS = (
    "package.json", "requirements*.txt", "constraints*.txt", "pyproject.toml", "Pipfile",
    "Cargo.toml", "go.mod", "Gemfile", "composer.json", "pom.xml", "build.gradle",
    "build.gradle.kts", "*.csproj", "Package.swift",
)  # fmt: skip

CONTAINER_DIRS = {"src", "lib", "app", "apps", "packages", "services", "internal", "pkg", "cmd"}


class Classifier:
    """Answers questions about a path, with user-supplied globs layered on the built-ins."""

    def __init__(
        self,
        *,
        tests: Iterable[str] = (),
        generated: Iterable[str] = (),
        sensitive: Iterable[str] = (),
        docs: Iterable[str] = (),
    ) -> None:
        self.extra_tests = tuple(tests)
        self.extra_generated = tuple(generated)
        self.sensitive = tuple(sensitive)
        self.extra_docs = tuple(docs)

    @staticmethod
    def _parts(path: str) -> tuple[list[str], str]:
        p = PurePosixPath(path)
        return [x.lower() for x in p.parts[:-1]], p.name

    def language(self, path: str) -> str | None:
        return LANGUAGES.get(PurePosixPath(path).suffix.lower())

    def is_test(self, path: str) -> bool:
        dirs, name = self._parts(path)
        if matches_any(path, self.extra_tests):
            return True
        return any(d in TEST_DIRS for d in dirs) or bool(TEST_NAME.match(name))

    def is_doc(self, path: str) -> bool:
        dirs, name = self._parts(path)
        if matches_any(path, self.extra_docs):
            return True
        stem = name.rsplit(".", 1)[0].lower()
        if PurePosixPath(name).suffix.lower() in DOC_EXTS:
            return True
        if stem in DOC_NAMES:
            return True
        return bool(dirs) and dirs[0] in {"docs", "doc", "documentation"}

    def is_lockfile(self, path: str) -> bool:
        name = PurePosixPath(path).name.lower()
        return name in LOCKFILES or name.endswith(".lock")

    def is_generated(self, path: str) -> bool:
        dirs, name = self._parts(path)
        if matches_any(path, self.extra_generated):
            return True
        if self.is_lockfile(path) or GENERATED_NAME.search(name):
            return True
        return any(d in GENERATED_DIRS for d in dirs)

    def is_pipeline(self, path: str) -> bool:
        return matches_any(path, PIPELINE_PATTERNS)

    def is_manifest(self, path: str) -> bool:
        return matches_any(path, MANIFESTS)

    def is_migration(self, path: str) -> bool:
        name = PurePosixPath(path).name.lower()
        if MIGRATION_DIR.search(path):
            return not self.is_doc(path)
        return name in {"schema.prisma", "schema.rb", "structure.sql"}

    def is_config(self, path: str) -> bool:
        """Configuration that changes behaviour without changing code.

        Pipeline files and dependency manifests have their own rules and are left out, except
        for the Python tool configs that live inside a manifest.
        """
        if self.is_pipeline(path) or self.is_generated(path) or self.is_test(path):
            return False
        if self.is_migration(path):
            return False
        dirs, name = self._parts(path)
        if ENV_TEMPLATE.search(name) and name.lower().startswith(".env"):
            return False
        if name.lower() in {"pyproject.toml", "setup.cfg"}:
            return True
        if self.is_manifest(path):
            return False
        if CONFIG_NAME.match(name):
            return True
        ext = PurePosixPath(name).suffix.lower()
        return ext in {".yml", ".yaml", ".toml", ".json", ".ini", ".xml"} and any(
            d in CONFIG_DIRS for d in dirs
        )

    def is_source(self, path: str) -> bool:
        if self.is_test(path) or self.is_generated(path) or self.is_migration(path):
            return False
        lang = self.language(path)
        return lang in SOURCE_LANGS

    def is_sensitive_path(self, path: str) -> bool:
        return matches_any(path, self.sensitive)

    def area(self, path: str) -> str:
        """The module a file belongs to, for judging how widely a change spreads."""
        parts = PurePosixPath(path).parts
        if len(parts) == 1:
            return "(root)"
        if parts[0].lower() in CONTAINER_DIRS and len(parts) > 2:
            return f"{parts[0]}/{parts[1]}"
        return parts[0]


_COMMENT_PREFIXES = {
    "hash": ("#",),
    "slash": ("//", "/*", "*"),
    "dash": ("--",),
}
_HASH_LANGS = {"python", "ruby", "shell", "powershell", "terraform", None}
_SLASH_LANGS = {
    "javascript", "typescript", "go", "java", "kotlin", "scala", "csharp", "php", "rust",
    "swift", "c", "cpp", "terraform",
}  # fmt: skip


def is_comment(text: str, language: str | None) -> bool:
    """Cheap comment check so pattern rules do not fire on commented-out code."""
    s = text.lstrip()
    if not s:
        return False
    if language in _HASH_LANGS and s.startswith("#"):
        return True
    if language in _SLASH_LANGS and s.startswith(_COMMENT_PREFIXES["slash"]):
        return True
    return language == "sql" and s.startswith("--")
