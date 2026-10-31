"""Rule modules. Importing a module registers its rules."""

from __future__ import annotations

import importlib

MODULES = (
    "configuration",
    "testing",
    "dependencies",
    "security",
    "pipeline",
    "database",
    "size",
    "churn",
    "interfaces",
    "codepatterns",
)


def load_all() -> None:
    for name in MODULES:
        importlib.import_module(f"{__name__}.{name}")
