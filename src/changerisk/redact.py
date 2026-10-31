"""Last line of defence: nothing that looks like a credential leaves the engine unmasked.

Rules mask what they quote, but the report also carries raw diff lines. Everything goes
through here before it is stored, printed or sent to the dashboard.
"""

from __future__ import annotations

import re

from .rules.configuration import SECRET_WORDS, is_env_file, key_tokens, parse_kv
from .rules.security import find_secrets, masked_line

_ENV_LINE = re.compile(r"^(\s*(?:export\s+)?[\w.-]+\s*=\s*).+$")
HIDDEN = "<hidden>"


def redact_line(path: str, text: str, *, config_file: bool = False) -> str:
    secrets = find_secrets(text)
    if secrets:
        text = masked_line(text, secrets)
    if is_env_file(path):
        m = _ENV_LINE.match(text)
        return m.group(1) + HIDDEN if m else text
    if config_file:
        kv = parse_kv(text, path)
        if kv and kv[1] and key_tokens(kv[0]) & SECRET_WORDS:
            return text.replace(kv[1], HIDDEN, 1)
    return text


def redact_text(text: str) -> str:
    """Mask credential-shaped values in free text such as a finding's detail sentence."""
    secrets = find_secrets(text)
    return masked_line(text, secrets) if secrets else text
