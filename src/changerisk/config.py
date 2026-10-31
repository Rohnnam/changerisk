"""Reading and checking `changerisk.toml`."""

from __future__ import annotations

import difflib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import Level, Severity
from .paths import Classifier

CONFIG_NAMES = ("changerisk.toml", ".changerisk.toml")
RESERVED_RULE_KEYS = {"enabled", "severity", "weight"}
GATE_CHOICES = ("never", "moderate", "high", "critical")

STARTER_CONFIG = """\
# ChangeRisk configuration. Every key is optional.

[gate]
# Fail the run when the risk level reaches this: never, moderate, high or critical.
fail_on = "high"

[history]
# Look at recent commit history for the files in the change (needs a full clone).
enabled = true
days = 90

[paths]
# Files to leave out of the analysis entirely.
ignore = ["docs/**", "**/*.md"]
# Extra globs on top of the built-in guesses.
tests = []
generated = []
sensitive = ["**/auth/**", "**/billing/**", "**/payments/**"]

[rules]
# Turn rules off by id. `changerisk rules` lists them.
disable = []

# Per-rule tuning. `severity` and `weight` work on every rule; other keys are the rule's own.
# [rules.SIZ001]
# medium_lines = 600
# high_lines = 1500
"""


class ConfigError(ValueError):
    """The configuration file is unreadable or has values we cannot use."""

    def __init__(self, problems: list[str], source: Path | None = None) -> None:
        self.problems = problems
        self.source = source
        where = f" in {source}" if source else ""
        super().__init__(f"invalid configuration{where}:\n  - " + "\n  - ".join(problems))


@dataclass
class RuleSettings:
    enabled: bool = True
    severity: Severity | None = None
    weight: float = 1.0
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    fail_on: Level | None = Level.HIGH
    history: bool = True
    history_days: int = 90
    ignore: tuple[str, ...] = ()
    tests: tuple[str, ...] = ()
    generated: tuple[str, ...] = ()
    docs: tuple[str, ...] = ()
    sensitive: tuple[str, ...] = ()
    rules: dict[str, RuleSettings] = field(default_factory=dict)
    source: Path | None = None

    def rule(self, rule_id: str) -> RuleSettings:
        return self.rules.get(rule_id, RuleSettings())

    def classifier(self) -> Classifier:
        return Classifier(
            tests=self.tests, generated=self.generated, sensitive=self.sensitive, docs=self.docs
        )


def find_config(root: Path) -> Path | None:
    for name in CONFIG_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError):
            return None
        if "changerisk" in data.get("tool", {}):
            return pyproject
    return None


def _suggest(word: str, choices: list[str]) -> str:
    close = difflib.get_close_matches(word, choices, n=1, cutoff=0.6)
    return f" (did you mean {close[0]!r}?)" if close else ""


def _str_list(value: Any, where: str, problems: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{where} must be a list of strings")
        return ()
    return tuple(value)


def load_config(
    root: Path,
    explicit: Path | None = None,
    rule_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> Config:
    """Load and validate configuration.

    `rule_options` maps each known rule id to its option defaults. When given, unknown rule ids
    and unknown or mistyped options are reported.
    """
    path = explicit or find_config(root)
    if path is None:
        return Config()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError([f"{path} does not exist"]) from None
    data = _toml(text, path)
    if path.name == "pyproject.toml":
        data = data.get("tool", {}).get("changerisk", {})
    return parse_config(data, path, rule_options)


def _toml(text: str, path: Path) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"not valid TOML: {exc}"], path) from None


def config_at_ref(
    root: Path, ref: str, rule_options: Mapping[str, Mapping[str, Any]] | None = None
) -> Config:
    """The configuration as committed at `ref`, or the defaults if there is none.

    A pull request must not be able to choose its own gate, so CI reads the configuration from the
    branch the change will merge into, not from the change itself.
    """
    from .gitops import run_git

    for name in CONFIG_NAMES:
        text = run_git(root, "show", f"{ref}:{name}", check=False)
        if text.strip():
            return parse_config(
                _toml(text, Path(f"{ref}:{name}")), Path(f"{ref}:{name}"), rule_options
            )
    text = run_git(root, "show", f"{ref}:pyproject.toml", check=False)
    if text.strip():
        label = Path(f"{ref}:pyproject.toml")
        table = _toml(text, label).get("tool", {}).get("changerisk")
        if table is not None:
            return parse_config(table, label, rule_options)
    return Config()


def parse_config(
    data: dict[str, Any],
    path: Path | None,
    rule_options: Mapping[str, Mapping[str, Any]] | None = None,
) -> Config:
    """Validate already-parsed configuration data."""
    problems: list[str] = []
    cfg = Config(source=path)

    top = {"gate", "history", "paths", "rules"}
    for key in data:
        if key not in top:
            problems.append(f"unknown section [{key}]{_suggest(key, sorted(top))}")

    gate = data.get("gate", {})
    if "fail_on" in gate:
        value = str(gate["fail_on"]).lower()
        if value not in GATE_CHOICES:
            problems.append(f"gate.fail_on must be one of {', '.join(GATE_CHOICES)}, got {value!r}")
        else:
            cfg.fail_on = None if value == "never" else Level.parse(value)

    hist = data.get("history", {})
    if "enabled" in hist:
        if isinstance(hist["enabled"], bool):
            cfg.history = hist["enabled"]
        else:
            problems.append("history.enabled must be true or false")
    if "days" in hist:
        days = hist["days"]
        if isinstance(days, int) and not isinstance(days, bool) and 1 <= days <= 3650:
            cfg.history_days = days
        else:
            problems.append("history.days must be a whole number between 1 and 3650")

    paths = data.get("paths", {})
    path_keys = {"ignore", "tests", "generated", "docs", "sensitive"}
    for key, value in paths.items():
        if key not in path_keys:
            problems.append(f"unknown key paths.{key}{_suggest(key, sorted(path_keys))}")
            continue
        setattr(cfg, key, _str_list(value, f"paths.{key}", problems))

    rules = data.get("rules", {})
    known = dict(rule_options) if rule_options is not None else None
    disabled = rules.get("disable", [])
    for rid in _str_list(disabled, "rules.disable", problems):
        if known is not None and rid not in known:
            problems.append(f"rules.disable names unknown rule {rid!r}{_suggest(rid, list(known))}")
        cfg.rules.setdefault(rid, RuleSettings()).enabled = False

    for rid, table in rules.items():
        if rid == "disable":
            continue
        if not isinstance(table, dict):
            problems.append(f"rules.{rid} must be a table")
            continue
        if known is not None and rid not in known:
            problems.append(f"unknown rule [rules.{rid}]{_suggest(rid, list(known))}")
            continue
        _read_rule_table(cfg.rules.setdefault(rid, RuleSettings()), rid, table, known, problems)

    if problems:
        raise ConfigError(problems, path)
    return cfg


def _read_rule_table(
    settings: RuleSettings,
    rid: str,
    table: dict[str, Any],
    known: dict[str, Mapping[str, Any]] | None,
    problems: list[str],
) -> None:
    defaults = known.get(rid, {}) if known is not None else {}
    for key, value in table.items():
        where = f"rules.{rid}.{key}"
        if key == "enabled":
            if isinstance(value, bool):
                settings.enabled = value
            else:
                problems.append(f"{where} must be true or false")
        elif key == "severity":
            try:
                settings.severity = Severity.parse(value)
            except ValueError as exc:
                problems.append(f"{where}: {exc}")
        elif key == "weight":
            if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0:
                settings.weight = float(value)
            else:
                problems.append(f"{where} must be a number, 0 or more")
        elif known is not None and key not in defaults:
            valid = sorted(set(defaults) | RESERVED_RULE_KEYS)
            problems.append(f"{where} is not an option of {rid}{_suggest(key, valid)}")
        else:
            default = defaults.get(key)
            if default is not None and not _same_kind(default, value):
                problems.append(f"{where} should be {type(default).__name__}, got {value!r}")
            else:
                settings.options[key] = value


def _same_kind(default: Any, value: Any) -> bool:
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if isinstance(default, (list, tuple)):
        return isinstance(value, list)
    return isinstance(value, type(default))
