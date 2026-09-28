"""Adapter-Schnittstelle für Datenquellen. Neue Quellen (CRM-Export, Registry, …) implementieren nur PracticeSource
und liefern kanonische PracticeRecords; Import-/Knowledge-Logik bleibt unverändert."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Protocol

from copilot.knowledge.records import PracticeRecord


@dataclass
class SourceRecord:
    row: int                               # Zeilennummer in der Quelle (für Fehlerberichte, ohne Inhalt)
    record: PracticeRecord | None = None
    errors: list[str] = field(default_factory=list)  # Fehlercodes, z. B. missing_name, invalid_plz


class PracticeSource(Protocol):
    name: str

    def fingerprint(self) -> str:
        """Stabiler Hash der Quelle (Audit/Nachvollziehbarkeit), kein Inhalt."""

    def records(self) -> Iterator[SourceRecord]: ...
