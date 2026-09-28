"""SourceProvider: entdeckt Praxis-Kandidaten aus EINER Quelle. Provider sind unabhängig voneinander austauschbar.

Rollen (Anpassung an die bestehende Architektur):
  * SourceProvider   (hier)              – findet Praxen/Ärzte („Wer gibt es im Gebiet?“)
  * ResearchProvider (research/provider) – reichert bekannte Praxen mit belegten Facts an („Was ist über sie bekannt?“)
Provider schreiben nie selbst in die Datenbank; Persistenz, Matching und Provenance übernimmt der Scanner.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

from copilot.domain.models import FactDraft
from copilot.errors import PolicyViolation, ProviderNotAvailable, ProviderNotCleared
from copilot.knowledge.records import PracticeRecord
from copilot.research.provider import SourceDraft
from copilot.scanner.area import Area


class ProviderStatus(str, Enum):
    READY = "ready"
    DISABLED = "disabled"                # in config/policies.yaml nicht eingeschaltet
    NOT_CLEARED = "not_cleared"          # Freigabe-Checkliste unvollständig
    NOT_IMPLEMENTED = "not_implemented"  # keine technische Zugriffsmethode vorhanden

    def __str__(self) -> str:
        return self.value


@dataclass
class Candidate:
    record: PracticeRecord
    provider: str
    source_ref: str                        # Herkunftsreferenz (nie Klartext-PII), z. B. file:<hash> oder eine URL
    row: int | None = None
    source: SourceDraft | None = None      # nur wenn die Quelle belegbare Facts liefert (Provenance)
    facts: list[FactDraft] = field(default_factory=list)


@dataclass(frozen=True)
class DiscoveryQuery:
    area: Area
    specialties: frozenset[str] = frozenset()   # Katalog-Codes; leer = alle
    max_results: int = 200                      # Obergrenze pro Abfrage (kein Massenabruf)


class SourceProvider(ABC):
    name: str
    description: str

    @abstractmethod
    def status(self) -> tuple[ProviderStatus, str]:
        """(Status, Klartext-Erläuterung)"""

    @abstractmethod
    def discover(self, query: DiscoveryQuery) -> Iterator[Candidate]: ...

    def ensure_ready(self) -> None:
        status, detail = self.status()
        if status is ProviderStatus.READY:
            return
        if status is ProviderStatus.DISABLED:
            raise PolicyViolation(f"Provider '{self.name}' ist nicht eingeschaltet: {detail}", code="provider_disabled")
        if status is ProviderStatus.NOT_CLEARED:
            raise ProviderNotCleared(f"Provider '{self.name}' ist nicht freigegeben: {detail}")
        raise ProviderNotAvailable(f"Provider '{self.name}' ist nicht verfügbar: {detail}")
