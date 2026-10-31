from changerisk.config import Config, RuleSettings
from changerisk.models import Severity
from changerisk.rules.configuration import parse_kv, parse_quantity

from .helpers import change, lines, run_rule

PROD_BEFORE = lines(
    "server:",
    "  request_timeout: 30",
    "  pool_size: 20",
    "  debug: false",
    "  tls_verify: true",
    "name: ledgerline",
)


def prod(old: str, new: str):
    assert old in PROD_BEFORE
    return change({"config/production.yml": (PROD_BEFORE, PROD_BEFORE.replace(old, new))})


# --- CFG001 -----------------------------------------------------------------


def test_cfg001_names_the_changed_keys_with_old_and_new_values():
    cs = prod("request_timeout: 30", "request_timeout: 300")
    (f,) = run_rule("CFG001", cs)
    assert "request_timeout changed from 30 to 300" in f.detail
    assert f.paths == ["config/production.yml"]
    assert f.evidence[0].text.strip() == "request_timeout: 300"
    assert f.evidence[0].line == 2


def test_cfg001_ordinary_config_is_low_production_is_medium():
    other = change(
        {"config/app.yml": (PROD_BEFORE, PROD_BEFORE.replace("name: ledgerline", "name: ledger"))}
    )
    assert run_rule("CFG001", other)[0].severity == Severity.LOW
    cs = prod("name: ledgerline", "name: ledger")
    assert run_rule("CFG001", cs)[0].severity == Severity.MEDIUM
    dev = change(
        {"config/dev.yml": (PROD_BEFORE, PROD_BEFORE.replace("pool_size: 20", "pool_size: 21"))}
    )
    assert run_rule("CFG001", dev)[0].severity == Severity.LOW


def test_cfg001_ignores_comment_only_edits():
    before = lines("# old note", "a: 1")
    after = lines("# new note", "a: 1")
    assert run_rule("CFG001", change({"config/app.yml": (before, after)})) == []


def test_cfg001_ignores_non_config_files():
    cs = change({"src/app.py": ("x = 1\n", "x = 2\n"), "README.md": ("a\n", "b\n")})
    assert run_rule("CFG001", cs) == []


def test_cfg001_reports_added_and_deleted_files():
    added = change({"config/new.yml": (None, "a: 1\nb: 2\n")})
    assert "was added" in run_rule("CFG001", added)[0].detail
    deleted = change({"config/old.yml": ("a: 1\n", None)})
    assert "was deleted" in run_rule("CFG001", deleted)[0].detail


def test_cfg001_json_and_python_settings_are_understood():
    js = change({"appsettings.json": ('{\n  "Retries": 3\n}\n', '{\n  "Retries": 5\n}\n')})
    assert "Retries changed from 3 to 5" in run_rule("CFG001", js)[0].detail
    py = change({"app/settings.py": ("TIMEOUT = 5\n", "TIMEOUT = 8\n")})
    assert "TIMEOUT changed from 5 to 8" in run_rule("CFG001", py)[0].detail


def test_cfg001_hides_values_for_secret_looking_keys():
    cs = change({"config/app.yml": ("api_token: abc123\n", "api_token: zzz999\n")})
    (f,) = run_rule("CFG001", cs)
    assert "abc123" not in f.detail and "zzz999" not in f.detail
    assert all("zzz999" not in e.text for e in f.evidence)
    assert "<hidden>" in f.detail


def test_cfg001_rule_can_be_disabled_by_the_engine_but_severity_override_applies():
    cs = prod("name: ledgerline", "name: ledger")
    cfg = Config(rules={"CFG001": RuleSettings(severity=Severity.MEDIUM)})
    # the override replaces the base; production still bumps it one step
    assert run_rule("CFG001", cs, cfg)[0].severity == Severity.HIGH


def test_inline_ignore_is_not_applied_to_cfg001_but_is_to_cfg002():
    before = "debug: false\n"
    after = "debug: true  # changerisk: ignore CFG002\n"
    cs = change({"config/app.yml": (before, after)})
    assert run_rule("CFG002", cs) == []
    assert run_rule("CFG001", cs) != []


# --- CFG002 -----------------------------------------------------------------


def test_cfg002_debug_switched_on_in_production_is_critical():
    cs = prod("debug: false", "debug: true")
    (f,) = run_rule("CFG002", cs)
    assert "debug was switched on" in f.detail
    assert f.severity == Severity.CRITICAL


def test_cfg002_tls_verification_switched_off():
    cs = change({"config/app.yml": ("tls_verify: true\n", "tls_verify: false\n")})
    (f,) = run_rule("CFG002", cs)
    assert "tls_verify was switched off" in f.detail
    assert f.severity == Severity.HIGH


def test_cfg002_debug_turned_off_is_fine():
    cs = change({"config/app.yml": ("debug: true\n", "debug: false\n")})
    assert run_rule("CFG002", cs) == []


def test_cfg002_wildcard_origin():
    before = "allowed_origins: ['https://app.example.com']\n"
    after = "allowed_origins: ['*']\n"
    (f,) = run_rule("CFG002", change({"config/cors.yml": (before, after)}))
    assert "accepts everything" in f.detail


def test_cfg002_python_settings_style():
    cs = change({"app/settings.py": ("DEBUG = False\n", "DEBUG = True\n")})
    assert len(run_rule("CFG002", cs)) == 1


def test_cfg002_does_not_fire_on_non_boolean_values():
    cs = change({"config/app.yml": ("auth_url: http://a\n", "auth_url: http://b\n")})
    assert run_rule("CFG002", cs) == []


# --- CFG003 -----------------------------------------------------------------


def test_cfg003_tenfold_timeout_is_high_in_production_but_never_critical():
    cs = prod("request_timeout: 30", "request_timeout: 300")
    (f,) = run_rule("CFG003", cs)
    assert "request_timeout rose 10x" in f.detail
    assert f.severity == Severity.HIGH  # a severe jump and a production file do not stack


def test_cfg003_a_moderate_change_is_medium_even_in_production():
    prod_cs = prod("pool_size: 20", "pool_size: 50")
    assert run_rule("CFG003", prod_cs)[0].severity == Severity.MEDIUM
    dev = change({"config/dev.yml": ("pool_size: 20\n", "pool_size: 50\n")})
    assert run_rule("CFG003", dev)[0].severity == Severity.MEDIUM
    dev_severe = change({"config/dev.yml": ("pool_size: 20\n", "pool_size: 500\n")})
    assert run_rule("CFG003", dev_severe)[0].severity == Severity.MEDIUM


def test_cfg002_suggested_tests_match_what_was_flipped():
    debug = run_rule("CFG002", prod("debug: false", "debug: true"))[0]
    assert any("stack trace" in t for t in debug.test_focus)
    assert not any("CSRF" in t for t in debug.test_focus)
    assert any("config/production.yml" in t for t in debug.test_focus)
    tls = run_rule("CFG002", prod("tls_verify: true", "tls_verify: false"))[0]
    assert any("TLS handshake" in t for t in tls.test_focus)


def test_cfg003_small_changes_are_ignored():
    cs = prod("pool_size: 20", "pool_size: 30")
    assert run_rule("CFG003", cs) == []


def test_cfg003_decrease_and_zero():
    cs = change({"config/app.yml": ("max_connections: 100\n", "max_connections: 10\n")})
    (f,) = run_rule("CFG003", cs)
    assert "fell to 1/10" in f.detail
    zero = change({"config/app.yml": ("rate_limit: 100\n", "rate_limit: 0\n")})
    assert "zero" in run_rule("CFG003", zero)[0].detail


def test_cfg003_understands_units_and_skips_mismatched_ones():
    cs = change({"config/app.yml": ("timeout: 30s\n", "timeout: 5m\n")})
    (f,) = run_rule("CFG003", cs)
    assert "rose 10x" in f.detail
    mixed = change({"config/app.yml": ("timeout: 30s\n", "timeout: 4096\n")})
    assert run_rule("CFG003", mixed) == []


def test_cfg003_factor_is_configurable():
    cs = prod("pool_size: 20", "pool_size: 30")
    cfg = Config(rules={"CFG003": RuleSettings(options={"factor": 1.4})})
    assert len(run_rule("CFG003", cs, cfg)) == 1


def test_cfg003_ignores_non_limit_keys():
    cs = change({"config/app.yml": ("port: 80\n", "port: 8000\n")})
    assert run_rule("CFG003", cs) == []


# --- CFG004 -----------------------------------------------------------------


def test_cfg004_env_file_is_flagged_and_values_never_appear():
    cs = change(
        {".env.production": (None, "STRIPE_KEY=sk_test_abcdef123456\nDB_HOST=db.internal\n")}
    )
    (f,) = run_rule("CFG004", cs)
    assert f.severity == Severity.HIGH
    assert "STRIPE_KEY" in f.detail
    blob = f.detail + " ".join(e.text for e in f.evidence)
    assert "abcdef123456" not in blob and "db.internal" not in blob


def test_cfg004_templates_are_fine():
    cs = change({".env.example": (None, "STRIPE_KEY=\n")})
    assert run_rule("CFG004", cs) == []


def test_cfg001_does_not_double_report_env_files():
    cs = change({".env": ("A=1\n", "A=2\n")})
    assert run_rule("CFG001", cs) == []
    assert len(run_rule("CFG004", cs)) == 1


# --- helpers ----------------------------------------------------------------


def test_parse_kv_shapes():
    assert parse_kv("  retries: 3", "a.yml") == ("retries", "3")
    assert parse_kv('  "retries": 3,', "a.json") == ("retries", "3")
    assert parse_kv("RETRIES=3  # inline", "a.env") == ("RETRIES", "3")
    assert parse_kv("name = 'x'", "a.toml") == ("name", "x")
    assert parse_kv("ENV PORT=8080", "Dockerfile") == ("PORT", "8080")
    assert parse_kv("FROM python:3.11", "Dockerfile") == ("FROM", "python:3.11")
    assert parse_kv("parent:", "a.yml") is None
    assert parse_kv("# retries: 3", "a.yml") is None
    assert parse_kv("- item", "a.yml") is None


def test_parse_quantity():
    assert parse_quantity("30") == (30.0, "")
    assert parse_quantity("2m") == (120.0, "time")
    assert parse_quantity("500ms") == (0.5, "time")
    assert parse_quantity("512Mi")[1] == "size"
    assert parse_quantity("fast") is None
