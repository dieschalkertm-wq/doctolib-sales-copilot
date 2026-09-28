"""Fact-Service: zeitabhängige, belegte Recherche-Aussagen.

Regeln (ARCHITECTURE §5/§7): Kein Fact ohne Quelle · Claims sind unveränderlich (neuer Fact ersetzt alten) ·
nur *aktuelle* Facts dürfen als Tatsache ausgegeben werden · veraltete werden markiert · Fehlendes ist 'unbekannt'.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from copilot.config import Policies
from copilot.domain.enums import EntityType, FactStatus, RobotsStatus, SourceType
from copilot.domain.models import Fact, FactDraft, Source
from copilot.domain.timeutil import utcnow
from copilot.errors import NotFound
from copilot.storage.research import ResearchRepository


@dataclass(frozen=True)
class FactView:
    fact: Fact
    source: Source
    now: datetime

    @property
    def is_current(self) -> bool:
        return self.fact.status is FactStatus.ACTIVE and (
            self.fact.stale_after is None or self.now < self.fact.stale_after)

    @property
    def is_stale(self) -> bool:
        return self.fact.status is FactStatus.ACTIVE and not self.is_current

    def statement(self) -> str:
        """Einziger Ausgabepfad für Fakten: immer mit Quelle + Zeitpunkt, veraltet ist markiert."""
        f, s = self.fact, self.source
        origin = s.url or s.publisher or s.source_type.value
        text = f"{f.key} = {f.value!r} — Quelle: {origin}, abgerufen {s.retrieved_at.date().isoformat()}"
        if self.is_stale:
            return f"VERALTET (seit {f.stale_after.date().isoformat()}, neu prüfen): {text}"  # type: ignore[union-attr]
        return f"BELEGT: {text}"


@dataclass
class FactProfile:
    current: list[FactView] = field(default_factory=list)
    stale: list[FactView] = field(default_factory=list)
    unknown_keys: list[str] = field(default_factory=list)


class FactService:
    def __init__(self, repo: ResearchRepository, policies: Policies):
        self.repo, self.policies = repo, policies

    def record(self, subject_type: EntityType, subject_id: int, draft: FactDraft, source_id: int, *,
               research_id: int | None = None, observed_at: datetime | None = None) -> Fact:
        if self.repo.get_source(source_id) is None:
            raise NotFound("Quelle nicht gefunden – ohne Quelle kein Fact", code="source_not_found")
        observed = observed_at or utcnow()
        fact = self.repo.insert_fact(Fact(
            subject_type=subject_type, subject_id=subject_id, key=draft.key, value=draft.value,
            source_id=source_id, research_id=research_id, confidence=draft.confidence, evidence=draft.evidence,
            observed_at=observed, stale_after=observed + timedelta(days=self.policies.staleness_days(draft.key))))
        for old in self.repo.facts_for(subject_type, subject_id, key=draft.key):
            if old.id != fact.id:
                self.repo.set_fact_status(old.id, FactStatus.SUPERSEDED, superseded_by=fact.id)  # type: ignore[arg-type]
        return fact

    def record_manual(self, subject_type: EntityType, subject_id: int, draft: FactDraft, *, note: str | None = None,
                      now: datetime | None = None) -> Fact:
        """Vom Nutzer erfasster Fact: eigene Quelle vom Typ 'manual' (Herkunft bleibt sichtbar)."""
        now = now or utcnow()
        source = self.repo.insert_source(Source(
            source_type=SourceType.MANUAL, publisher="manuelle Erfassung", retrieved_at=now,
            robots_status=RobotsStatus.NOT_APPLICABLE, tos_ref=note, reliability=3))
        return self.record(subject_type, subject_id, draft, source.id, observed_at=now)  # type: ignore[arg-type]

    def view(self, fact: Fact, now: datetime | None = None) -> FactView:
        source = self.repo.get_source(fact.source_id)
        if source is None:  # durch FK ausgeschlossen; defensiv, damit nie unbelegt ausgegeben wird
            raise NotFound("Quelle fehlt", code="source_not_found")
        return FactView(fact, source, now or utcnow())

    def profile(self, subject_type: EntityType, subject_id: int, now: datetime | None = None) -> FactProfile:
        now = now or utcnow()
        profile = FactProfile()
        for fact in self.repo.facts_for(subject_type, subject_id):
            view = self.view(fact, now)
            (profile.current if view.is_current else profile.stale).append(view)
        have = {v.fact.key for v in profile.current}
        profile.unknown_keys = [k for k in self.policies.expected_fact_keys if k not in have]
        return profile
