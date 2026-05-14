"""Shared local .env loader for workspace-only secrets."""

from __future__ import annotations

import os
from pathlib import Path


LOCAL_SECRETS_DIR = Path(__file__).resolve().parents[1] / ".local-secrets"
DEFAULT_ENV_PATH = LOCAL_SECRETS_DIR / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
            value = value[1:-1]
        values[key] = value
    return values


def load_local_env_values() -> dict[str, str]:
    return parse_env_file(DEFAULT_ENV_PATH)


def get_secret(*keys: str) -> str | None:
    for key in keys:
        value = os.environ.get(key)
        if value:
            return value
    local_values = load_local_env_values()
    for key in keys:
        value = local_values.get(key)
        if value:
            return value
    return None
