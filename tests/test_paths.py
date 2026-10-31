import pytest

from changerisk.paths import Classifier, compile_glob, is_comment, matches_any


@pytest.mark.parametrize(
    ("pattern", "path", "expected"),
    [
        ("*.md", "README.md", True),
        ("*.md", "docs/guide/intro.md", True),
        ("docs/**", "docs/a/b.txt", True),
        ("docs/**", "src/docs/a.txt", False),
        ("src/*.py", "src/a.py", True),
        ("src/*.py", "src/pkg/a.py", False),
        ("**/auth/**", "src/auth/login.py", True),
        ("**/auth/**", "auth/login.py", True),
        ("vendor/", "vendor/lib/x.js", True),
        ("/setup.py", "setup.py", True),
        ("/setup.py", "pkg/setup.py", False),
        ("Dockerfile*", "svc/Dockerfile.prod", True),
        ("file?.txt", "file1.txt", True),
        ("file?.txt", "file12.txt", False),
        ("*.MD", "readme.md", True),
    ],
)
def test_glob_matching(pattern, path, expected):
    assert bool(compile_glob(pattern).match(path)) is expected


def test_matches_any_with_empty_patterns():
    assert not matches_any("a.py", [])


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_billing.py",
        "test_billing.py",
        "src/billing_test.py",
        "web/src/cart.test.ts",
        "web/src/cart.spec.jsx",
        "pkg/store_test.go",
        "src/main/java/FooTest.java",
        "spec/models/user_spec.rb",
        "conftest.py",
        "app/__tests__/helpers.js",
    ],
)
def test_test_paths(classifier, path):
    assert classifier.is_test(path)


@pytest.mark.parametrize(
    "path", ["src/billing.py", "src/contest.py", "latest/notes.py", "src/attestation.go"]
)
def test_non_test_paths(classifier, path):
    assert not classifier.is_test(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env", ".env.production", "config/settings.yml", "settings.py", "app/settings_prod.py",
        "src/application.yml", "docker-compose.prod.yml", "Dockerfile", "infra/main.tf",
        "k8s/deploy.yaml", "nginx.conf", "pyproject.toml", "pytest.ini", "webpack.config.js",
        "charts/api/values.yaml",
    ],
)  # fmt: skip
def test_config_paths(classifier, path):
    assert classifier.is_config(path)


@pytest.mark.parametrize(
    "path",
    [
        ".env.example", ".env.sample", ".github/workflows/ci.yml", "package.json",
        "requirements.txt", "package-lock.json", "tests/config.yml", "src/app.py",
        "migrations/0001.sql", "docs/config.md",
    ],
)  # fmt: skip
def test_not_config_paths(classifier, path):
    assert not classifier.is_config(path)


def test_lockfiles_and_generated(classifier):
    assert classifier.is_lockfile("web/yarn.lock")
    assert classifier.is_lockfile("Cargo.lock")
    assert classifier.is_generated("dist/app.min.js")
    assert classifier.is_generated("node_modules/x/index.js")
    assert classifier.is_generated("api/service_pb2.py")
    assert not classifier.is_generated("src/service.py")


def test_docs(classifier):
    assert classifier.is_doc("README.md")
    assert classifier.is_doc("docs/setup.html")
    assert classifier.is_doc("LICENSE")
    assert not classifier.is_doc("src/app.py")


def test_pipeline_and_migration_paths(classifier):
    assert classifier.is_pipeline(".github/workflows/release.yml")
    assert classifier.is_pipeline("Jenkinsfile")
    assert classifier.is_pipeline("ci/Jenkinsfile.deploy")
    assert not classifier.is_pipeline("workflows/release.yml")
    assert classifier.is_migration("db/migrate/20240101_add_users.rb")
    assert classifier.is_migration("app/migrations/0002_auto.py")
    assert classifier.is_migration("prisma/schema.prisma")
    assert not classifier.is_migration("docs/migrations/guide.md")


def test_source_excludes_tests_generated_and_migrations(classifier):
    assert classifier.is_source("src/app.py")
    assert classifier.is_source("web/app.tsx")
    assert not classifier.is_source("tests/test_app.py")
    assert not classifier.is_source("dist/bundle.js")
    assert not classifier.is_source("app/migrations/0002_auto.py")
    assert not classifier.is_source("notes.txt")


def test_user_globs_extend_the_builtins():
    c = Classifier(tests=["qa/**"], generated=["gen/**"], sensitive=["src/ledger/**"])
    assert c.is_test("qa/smoke.py")
    assert c.is_generated("gen/models.py")
    assert c.is_sensitive_path("src/ledger/post.py")
    assert not c.is_sensitive_path("src/other/post.py")


def test_area():
    c = Classifier()
    assert c.area("README.md") == "(root)"
    assert c.area("src/billing/invoice.py") == "src/billing"
    assert c.area("src/main.py") == "src"
    assert c.area("web/app.js") == "web"
    assert c.area("packages/ui/button.tsx") == "packages/ui"


def test_comment_detection():
    assert is_comment("  # note", "python")
    assert is_comment("// note", "javascript")
    assert is_comment(" * block", "java")
    assert is_comment("-- note", "sql")
    assert not is_comment("#include <x.h>", "c")
    assert not is_comment("x = 1  # trailing", "python")
    assert not is_comment("", "python")
