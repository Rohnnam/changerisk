"""Turn findings into points, a 0-100 score and a level.

The model is deliberately small enough to check by hand:

* each finding is worth points by severity, times the rule's weight
* repeat hits of the same rule count for half, then a quarter, and so on
* the points add up to a total, and the score is 100 * (1 - exp(-total / 40))
* a critical finding means the level is at least high, a high one at least moderate
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from .config import Config
from .models import Finding, Level, Severity

POINTS = {
    Severity.INFO: 0.0,
    Severity.LOW: 3.0,
    Severity.MEDIUM: 8.0,
    Severity.HIGH: 16.0,
    Severity.CRITICAL: 30.0,
}
DECAY = 0.5
SCALE = 40.0
# A score at or above each bound belongs to the next level up.
BANDS = ((25, Level.MODERATE), (50, Level.HIGH), (75, Level.CRITICAL))
BAND_FLOOR = {Level.LOW: 0, Level.MODERATE: 25, Level.HIGH: 50, Level.CRITICAL: 75}
SEVERITY_FLOOR = {Severity.CRITICAL: Level.HIGH, Severity.HIGH: Level.MODERATE}


@dataclass
class Score:
    points: float
    value: int
    level: Level
    floor_note: str | None = None


def level_for(score: int) -> Level:
    level = Level.LOW
    for bound, lv in BANDS:
        if score >= bound:
            level = lv
    return level


def value_for(points: float) -> int:
    return round(100 * (1 - math.exp(-max(points, 0.0) / SCALE)))


def apply_points(findings: Iterable[Finding], config: Config) -> list[Finding]:
    """Fill in `points` on each finding, applying decay to repeats of the same rule."""
    by_rule: dict[str, list[Finding]] = defaultdict(list)
    ordered = list(findings)
    for f in ordered:
        by_rule[f.rule_id].append(f)
    for rule_id, group in by_rule.items():
        weight = config.rule(rule_id).weight
        group.sort(key=lambda f: POINTS[f.severity], reverse=True)
        for rank, f in enumerate(group):
            f.points = POINTS[f.severity] * weight * (DECAY**rank)
    return ordered


def score(findings: list[Finding]) -> Score:
    total = sum(f.points for f in findings)
    value = value_for(total)
    level = level_for(value)
    note = None

    worst = max(
        (f for f in findings if f.severity in SEVERITY_FLOOR),
        key=lambda f: f.severity,
        default=None,
    )
    if worst is not None:
        floor = SEVERITY_FLOOR[worst.severity]
        if floor > level:
            note = (
                f"Raised to {floor.label} because of a {worst.severity.label} finding "
                f"({worst.rule_id}); the points alone would give {level.label}."
            )
            level = floor
            value = max(value, BAND_FLOOR[floor])
    return Score(points=total, value=value, level=level, floor_note=note)
