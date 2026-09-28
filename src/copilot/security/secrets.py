"""Secrets nur über Umgebung / .env (gitignored). Nie in config/*.yaml, nie in Logs."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

from copilot.errors import ConfigError

_SECRET_KEY = re.compile(r"(?i)(secret|token|password|passwd|api[_-]?key|credential|private[_-]?key)")


class Secret:
    """Wrapper, dessen repr/str den Wert nie preisgibt."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    __str__ = __repr__


def get_secret(name: str, env: Mapping[str, str] | None = None, *, required: bool = False) -> Secret | None:
    value = (env if env is not None else os.environ).get(name)
    if not value:
        if required:
            raise ConfigError(f"Secret '{name}' fehlt (Umgebungsvariable oder .env setzen)", code="secret_missing")
        return None
    return Secret(value)


def assert_no_secret_keys(data: Any, where: str = "config") -> None:
    """Konfig-Dateien sind committbar: Schlüssel, die nach Secrets aussehen, sind verboten."""
    if isinstance(data, Mapping):
        for key, value in data.items():
            if _SECRET_KEY.search(str(key)):
                raise ConfigError(
                    f"{where}: Schlüssel '{key}' sieht nach Secret aus – Secrets gehören in die Umgebung/.env",
                    code="secret_in_config",
                )
            assert_no_secret_keys(value, where)
    elif isinstance(data, list):
        for item in data:
            assert_no_secret_keys(item, where)
