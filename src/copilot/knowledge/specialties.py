"""Fachrichtungs-Katalog (config/specialties.yaml): Seed + Alias-Auflösung. Unbekanntes wird nie geraten."""

from __future__ import annotations

import re
from pathlib import Path

from copilot.config import load_yaml
from copilot.domain.normalize import fold
from copilot.errors import ConfigError
from copilot.storage.knowledge import KnowledgeRepository


class SpecialtyCatalog:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        self._alias: dict[str, str] = {}
        for e in entries:
            for label in [e["code"], e["name"], *e.get("aliases", [])]:
                self._alias[fold(label)] = e["code"]

    @classmethod
    def load(cls, config_dir: Path) -> "SpecialtyCatalog":
        data = load_yaml(config_dir / "specialties.yaml") or {}
        entries = data.get("specialties")
        if not isinstance(entries, list) or not all("code" in e and "name" in e for e in entries):
            raise ConfigError("specialties.yaml ungültig", code="config_invalid")
        return cls(entries)

    def resolve(self, label: str) -> str | None:
        return self._alias.get(fold(label))

    def seed(self, repo: KnowledgeRepository) -> None:
        for e in self.entries:
            repo.upsert_specialty(e["code"], e["name"])


def split_labels(cell: str) -> list[str]:
    """'Kardiologie; Innere Medizin / Internist' -> Einzelbezeichnungen."""
    return [p.strip() for p in re.split(r"[;/|\n]+", cell) if p.strip()]
