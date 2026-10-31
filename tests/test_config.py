import pytest

from changerisk.config import Config, ConfigError, config_at_ref, find_config, load_config
from changerisk.models import Level, Severity
from changerisk.rules import load_all
from changerisk.rules.base import option_defaults


@pytest.fixture(autouse=True)
def _rules():
    load_all()


def write(tmp_path, text, name="changerisk.toml"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_no_file_means_defaults(tmp_path):
    cfg = load_config(tmp_path, rule_options=option_defaults())
    assert cfg.fail_on == Level.HIGH and cfg.source is None and cfg.history is True


def test_full_example_round_trip(tmp_path):
    write(
        tmp_path,
        """
[gate]
fail_on = "moderate"
[history]
enabled = false
days = 30
[paths]
ignore = ["docs/**"]
sensitive = ["src/ledger/**"]
[rules]
disable = ["COD003"]
[rules.SIZ001]
medium_lines = 100
severity = "high"
weight = 1.5
""",
    )
    cfg = load_config(tmp_path, rule_options=option_defaults())
    assert cfg.fail_on == Level.MODERATE
    assert (cfg.history, cfg.history_days) == (False, 30)
    assert cfg.ignore == ("docs/**",) and cfg.sensitive == ("src/ledger/**",)
    assert cfg.rule("COD003").enabled is False
    siz = cfg.rule("SIZ001")
    assert (siz.severity, siz.weight, siz.options) == (Severity.HIGH, 1.5, {"medium_lines": 100})
    assert cfg.rule("CFG001").enabled is True  # untouched rules get defaults


def test_never_turns_the_gate_off(tmp_path):
    write(tmp_path, '[gate]\nfail_on = "never"\n')
    assert load_config(tmp_path).fail_on is None


def test_pyproject_table(tmp_path):
    write(tmp_path, '[tool.changerisk.gate]\nfail_on = "critical"\n', "pyproject.toml")
    assert find_config(tmp_path).name == "pyproject.toml"
    assert load_config(tmp_path).fail_on == Level.CRITICAL


def test_pyproject_without_our_table_is_ignored(tmp_path):
    write(tmp_path, "[tool.ruff]\nline-length = 100\n", "pyproject.toml")
    assert find_config(tmp_path) is None


def test_changerisk_toml_wins_over_pyproject(tmp_path):
    write(tmp_path, '[tool.changerisk.gate]\nfail_on = "critical"\n', "pyproject.toml")
    write(tmp_path, '[gate]\nfail_on = "moderate"\n')
    assert load_config(tmp_path).fail_on == Level.MODERATE


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        ('[gat]\nfail_on = "high"\n', "unknown section [gat] (did you mean 'gate'?)"),
        ('[gate]\nfail_on = "hihg"\n', "gate.fail_on must be one of"),
        ("[history]\ndays = 0\n", "history.days must be a whole number"),
        ('[paths]\nignroe = ["a"]\n', "unknown key paths.ignroe (did you mean 'ignore'?)"),
        ('[paths]\nignore = "docs"\n', "paths.ignore must be a list of strings"),
        ('[rules]\ndisable = ["CFG01"]\n', "unknown rule 'CFG01' (did you mean 'CFG001'?)"),
        ("[rules.NOPE1]\nweight = 1\n", "unknown rule [rules.NOPE1]"),
        (
            "[rules.SIZ001]\nmedium_line = 100\n",
            "rules.SIZ001.medium_line is not an option of SIZ001 (did you mean 'medium_lines'?)",
        ),
        ('[rules.SIZ001]\nmedium_lines = "lots"\n', "rules.SIZ001.medium_lines should be int"),
        ('[rules.SIZ001]\nseverity = "scary"\n', "unknown severity 'scary'"),
        ("[rules.SIZ001]\nweight = -1\n", "must be a number, 0 or more"),
        ("[rules.SIZ001]\nenabled = 1\n", "must be true or false"),
    ],
)
def test_validation_messages(tmp_path, text, fragment):
    write(tmp_path, text)
    with pytest.raises(ConfigError) as err:
        load_config(tmp_path, rule_options=option_defaults())
    assert fragment in str(err.value)


def test_all_problems_are_reported_together(tmp_path):
    write(tmp_path, '[gate]\nfail_on = "x"\n[history]\ndays = 0\n')
    with pytest.raises(ConfigError) as err:
        load_config(tmp_path)
    assert len(err.value.problems) == 2


def test_invalid_toml_and_missing_explicit_file(tmp_path):
    write(tmp_path, "[gate\n")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(tmp_path)
    with pytest.raises(ConfigError, match="does not exist"):
        load_config(tmp_path, explicit=tmp_path / "nope.toml")


def test_classifier_uses_configured_globs():
    cfg = Config(tests=("qa/**",), sensitive=("src/ledger/**",))
    c = cfg.classifier()
    assert c.is_test("qa/smoke.py") and c.is_sensitive_path("src/ledger/x.py")


def test_config_at_ref_reads_the_committed_file_not_the_working_copy(repo):
    repo.write("changerisk.toml", '[gate]\nfail_on = "moderate"\n')
    base = repo.commit("add config")
    repo.write("changerisk.toml", '[gate]\nfail_on = "never"\n')
    cfg = config_at_ref(repo.root, base, option_defaults())
    assert cfg.fail_on == Level.MODERATE


def test_config_at_ref_understands_pyproject_and_missing_files(repo):
    repo.write("pyproject.toml", '[tool.changerisk.gate]\nfail_on = "critical"\n')
    with_cfg = repo.commit("pyproject config")
    assert config_at_ref(repo.root, with_cfg).fail_on == Level.CRITICAL
    repo.write("pyproject.toml", "[tool.ruff]\nline-length = 100\n")
    without = repo.commit("no changerisk table")
    assert config_at_ref(repo.root, without).fail_on == Level.HIGH  # defaults


def test_config_at_ref_validates_what_it_reads(repo):
    repo.write("changerisk.toml", "[gat]\nfail_on = 1\n")
    base = repo.commit("bad config")
    with pytest.raises(ConfigError, match="unknown section"):
        config_at_ref(repo.root, base, option_defaults())
