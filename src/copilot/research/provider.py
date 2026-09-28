"""ResearchProvider-Abstraktion. Konkrete Provider (Praxis-Website heute; Events, Registries, … später) liefern
ausschließlich Source-Entwurf + Fact-Entwürfe. Persistenz, Zeitstempel und Staleness macht der ResearchService."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime

from copilot.domain.enums import EntityType, RobotsStatus, SourceType
from copilot.domain.models import FactDraft


@dataclass(frozen=True)
class ResearchRequest:
    subject_type: EntityType
    subject_id: int
    url: str | None = None


@dataclass
class SourceDraft:
    source_type: SourceType
    url: str | None
    publisher: str | None
    robots_status: RobotsStatus
    reliability: int
    tos_ref: str | None = None
    published_at: datetime | None = None
    content_hash: str | None = None
    raw_content: bytes | None = None


@dataclass
class ProviderOutput:
    source: SourceDraft
    facts: list[FactDraft] = field(default_factory=list)


class ResearchProvider(ABC):
    name: str
    kind: str

    @abstractmethod
    def collect(self, request: ResearchRequest) -> ProviderOutput:
        """Darf PolicyViolation/FetchError werfen. Darf nichts persistieren und keine Fakten erfinden."""
