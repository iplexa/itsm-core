"""Minimal, dependency-free configuration for Help/SimpleOne access."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class ConfigError(RuntimeError):
    """Required connection settings are missing."""


def _load_dotenv() -> dict[str, str]:
    path = Path.cwd() / ".env"
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        result[key.strip()] = value
    return result


@dataclass(frozen=True)
class Settings:
    base_url: str = ""
    username: str = ""
    password: str = ""
    timeout: float = 60.0

    def require_credentials(self) -> tuple[str, str]:
        if not self.base_url:
            raise ConfigError("HELP_BASE_URL не задан")
        if not self.username or not self.password:
            raise ConfigError("HELP_SERVICE_USERNAME / HELP_SERVICE_PASSWORD не заданы")
        return self.username, self.password

    def __repr__(self) -> str:
        return (
            f"Settings(base_url={self.base_url!r}, username={self.username!r}, "
            "password=<hidden>, timeout=" + repr(self.timeout) + ")"
        )


def build_settings(env: dict[str, str] | None = None) -> Settings:
    source = _load_dotenv()
    source.update(os.environ)
    if env:
        source.update(env)
    base_url = source.get("HELP_BASE_URL", "").strip().rstrip("/")
    return Settings(
        base_url=base_url,
        username=source.get("HELP_SERVICE_USERNAME", "").strip(),
        password=source.get("HELP_SERVICE_PASSWORD", ""),
        timeout=float(source.get("HELP_TIMEOUT", "60")),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return build_settings()
