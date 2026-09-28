"""ProspectListBuilder: verdichtet Praxis + Gebietstreffer + Worklist-Bewertung zu einer Arbeitslistenzeile.
Alle Aussagen stammen aus gespeicherten, belegten Daten; Fehlendes steht als „unbekannt“."""

from __future__ import annotations

from datetime import datetime

from copilot.domain.enums import EntityType
from copilot.domain.geo import format_distance
from copilot.domain.models import Practice
from copilot.knowledge.network import NetworkService
from copilot.pipeline.worklist import DOCTOLIB_SIGNAL_KEYS, WorklistItem
from copilot.research.facts import FactProfile, FactService
from copilot.scanner.area import AreaMatch
from copilot.scanner.result import ScanItem
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.network import NetworkRepository
from copilot.storage.pipeline import PipelineRepository
from copilot.storage.research import ResearchRepository

_DOCTOLIB_LABEL = {"doctolib_link_present": "Link auf der Praxis-Website", "doctolib_profile_public": "öffentliches Profil"}


class ProspectListBuilder:
    def __init__(self, knowledge: KnowledgeRepository, research: ResearchRepository, network: NetworkRepository,
                 pipeline: PipelineRepository, facts: FactService, network_service: NetworkService):
        self.knowledge, self.research, self.network = knowledge, research, network
        self.pipeline, self.facts, self.network_service = pipeline, facts, network_service

    def build_item(self, practice: Practice, match: AreaMatch | None, wl: WorklistItem, now: datetime,
                   new_ids: set[int]) -> ScanItem:
        pid: int = practice.id  # type: ignore[assignment]
        profile = self.facts.profile(EntityType.PRACTICE, pid, now)
        return ScanItem(
            practice=practice,
            specialties=[s.name for s in self.knowledge.practice_specialties(pid)],
            doctors=[f"{d.title + ' ' if d.title else ''}{d.full_name}" for d in self.knowledge.doctors_of(pid)],
            match=match, distance=self._distance(match),
            origins=self._origins(pid), status=wl.status, stage=wl.stage,
            research_status=self._research_status(pid, profile),
            doctolib_signal=self._doctolib(profile),
            website=practice.website_url,
            facts=[v.statement() for v in profile.current + profile.stale],
            network=self._network(pid), worklist=wl, is_new=pid in new_ids)

    @staticmethod
    def _distance(match: AreaMatch | None) -> str:
        if match is None or match.distance_km is None:
            return "–"
        text = format_distance(match.distance_km, match.uncertainty_km)
        return text + (" · möglicherweise im Radius" if match.certainty.value == "possible" else "")

    def _origins(self, pid: int) -> list[str]:
        rows = self.knowledge.origins_of(pid)
        if not rows:
            return ["unbekannt (kein Herkunftsnachweis gespeichert)"]
        return [f"{r['provider']} ({r['source_ref']}, zuletzt {r['last_seen_at'][:10]})" for r in rows]

    def _research_status(self, pid: int, profile: FactProfile) -> str:
        if profile.current:
            latest = max(v.source.retrieved_at for v in profile.current).date().isoformat()
            return f"recherchiert (Stand {latest}, {len(profile.current)} aktuelle Facts)"
        if profile.stale:
            latest = max(v.source.retrieved_at for v in profile.stale).date().isoformat()
            return f"veraltet (Stand {latest}) – erneuern"
        runs = self.research.list_research(EntityType.PRACTICE, pid)
        if runs and runs[0]["status"] in ("blocked", "failed"):
            return f"nicht möglich ({runs[0]['status']}: {runs[0]['error_code']})"
        return "nicht recherchiert"

    @staticmethod
    def _doctolib(profile: FactProfile) -> str:
        for views, prefix in ((profile.current, "erkennbar"), (profile.stale, "veraltet")):
            for v in views:
                if v.fact.key in DOCTOLIB_SIGNAL_KEYS:
                    return (f"{prefix} – {_DOCTOLIB_LABEL[v.fact.key]} (belegt, Fact #{v.fact.id}, "
                            f"Stand {v.source.retrieved_at.date().isoformat()})")
        return "unbekannt (nicht belegt)"

    def _network(self, pid: int) -> list[str]:
        customers = self.pipeline.customer_practice_ids()
        lines = []
        for rel in self.network.for_entity(EntityType.PRACTICE, pid, direction="in"):
            who = f"Kundenpraxis #{rel.from_id}" if rel.from_id in customers else f"Praxis #{rel.from_id}"
            dist = (f", {format_distance(rel.distance_km, rel.distance_uncertainty_km or 0.0)}"
                    if rel.distance_km is not None else "")
            lines.append(f"{who} → diese Praxis ({rel.rel_type.value}): {self.network_service.describe(rel)}{dist}")
        return lines
