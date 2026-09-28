"""Konfiguration: Settings aus Umgebung/.env, fachliche Konfig aus config/*.yaml (ohne Secrets)."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from copilot.errors import ConfigError
from copilot.security.secrets import assert_no_secret_keys

DEFAULT_USER_AGENT = "doctolib-sales-copilot/0.1 (persoenlicher Recherche-Assistent)"


def load_dotenv(path: Path) -> dict[str, str]:
    """Minimaler .env-Parser (KEY=VALUE, # Kommentare). Kein Export in os.environ."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


def load_env(home: Path | None = None) -> dict[str, str]:
    """Prozess-Umgebung hat Vorrang vor .env."""
    home = home or Path(os.environ.get("COPILOT_HOME", Path.cwd()))
    return {**load_dotenv(home / ".env"), **os.environ}


@dataclass(frozen=True)
class Settings:
    home: Path
    config_dir: Path
    data_dir: Path
    db_path: Path
    raw_cache_dir: Path
    log_level: str
    user_agent: str
    actor: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = env if env is not None else load_env()
        home = Path(env.get("COPILOT_HOME", Path.cwd())).resolve()
        data_dir = Path(env.get("COPILOT_DATA_DIR", home / "data")).resolve()
        return cls(
            home=home,
            config_dir=Path(env.get("COPILOT_CONFIG_DIR", home / "config")).resolve(),
            data_dir=data_dir,
            db_path=Path(env.get("COPILOT_DB_PATH", data_dir / "copilot.sqlite3")).resolve(),
            raw_cache_dir=data_dir / "raw_cache",
            log_level=env.get("COPILOT_LOG_LEVEL", "INFO"),
            user_agent=env.get("COPILOT_USER_AGENT", DEFAULT_USER_AGENT),
            actor=env.get("COPILOT_ACTOR", "cli-user"),
        )


def load_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"Konfigurationsdatei fehlt: {path.name}", code="config_missing")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path.name}: ungültiges YAML", code="config_invalid") from exc
    assert_no_secret_keys(data, path.name)
    return data


# --- policies.yaml -----------------------------------------------------------------------


class ResearchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rate_limit_seconds: float = Field(default=1.0, ge=1.0)  # ARCHITECTURE §7: max. 1 req/Domäne/Sek.
    timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    max_bytes: int = Field(default=2_000_000, gt=0)
    max_redirects: int = Field(default=3, ge=0, le=5)
    allowed_domains: list[str] = Field(default_factory=list)  # leer => alles gesperrt
    booking_signal_domains: dict[str, str] = Field(default_factory=dict)


class Policies(BaseModel):
    model_config = ConfigDict(extra="forbid")
    research: ResearchPolicy = ResearchPolicy()
    fact_staleness_days: dict[str, int] = Field(default_factory=lambda: {"default": 180})
    expected_fact_keys: list[str] = Field(default_factory=list)

    def staleness_days(self, key: str) -> int:
        return self.fact_staleness_days.get(key, self.fact_staleness_days.get("default", 180))


def load_policies(config_dir: Path) -> Policies:
    data = load_yaml(config_dir / "policies.yaml") or {}
    try:
        return Policies.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"policies.yaml ungültig: {exc.error_count()} Fehler", code="config_invalid") from exc
