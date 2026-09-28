"""Arbeitslisten ("Heute Saarbrücken"): deterministisch, jede Punktvergabe mit Begründung.
Fehlende Information erzeugt keine Punkte, sondern eine 'Unbekannt'-Zeile und eine nächste Aktion."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from copilot.domain.enums import EntityType, RelationOrigin, RelationType
from copilot.domain.geo import format_distance
from copilot.domain.models import Practice
from copilot.domain.territory import Territory
from copilot.domain.timeutil import utcnow
from copilot.errors import ValidationFailed
from copilot.pipeline.scoring import ScoringConfig
from copilot.research.facts import FactService
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.network import NetworkRepository
from copilot.storage.pipeline import PipelineRepository

DOCTOLIB_SIGNAL_KEYS = frozenset({"doctolib_link_present", "doctolib_profile_public"})

NEXT_ACTIONS = {
    "find_website": "Website der Praxis ermitteln (manuell) und Domain prüfen/freigeben",
    "research_website": "Website-Recherche ausführen (copilot research website)",
    "refresh_research": "Veraltete Recherche erneuern",
    "prepare_outreach": "Ansprache vorbereiten (Entwürfe folgen ab Phase 2)",
}


@dataclass
class Reason:
    criterion: str
    points: float
    explanation: str
    fact_ids: list[int] = field(default_factory=list)


@dataclass
class WorklistItem:
    practice: Practice
    score: float
    reasons: list[Reason]
    unknowns: list[str]
    next_action: str
    status: str  # "prospect" | "unassigned"
    stage: str | None = None


@dataclass
class Worklist:
    scope_label: str
    items: list[WorklistItem]
    excluded: Counter = field(default_factory=Counter)
    excluded_practices: list[tuple[Practice, str]] = field(default_factory=list)   # (Praxis, Grund) – nichts verschwindet still


class WorklistService:
    def __init__(self, knowledge: KnowledgeRepository, pipeline: PipelineRepository, network: NetworkRepository,
                 facts: FactService, scoring: ScoringConfig, territory: Territory):
        self.knowledge, self.pipeline, self.network = knowledge, pipeline, network
        self.facts, self.scoring, self.territory = facts, scoring, territory

    def build(self, scope_text: str, *, now: datetime | None = None, limit: int | None = None) -> Worklist:
        now = now or utcnow()
        scope = self.territory.parse_scope(scope_text)
        if scope is None:
            known = sorted({p.name for p in self.territory.places} | {r.name for r in self.territory.regions.values()})
            raise ValidationFailed(f"Unbekanntes Gebiet '{scope_text}'. Bekannt: {', '.join(known)}", code="unknown_scope")
        if scope.kind == "place":
            practices = [p for p in self.knowledge.list_practices(region=scope.place.region)  # type: ignore[union-attr]
                         if self.territory.find_place(p.ort) == scope.place]
        else:
            practices = self.knowledge.list_practices(region=scope.region.key)  # type: ignore[union-attr]

        result = self.evaluate_many(practices, now=now, scope_label=scope.label)
        if limit is not None:
            result.items = result.items[:limit]
        return result

    def evaluate_many(self, practices: list[Practice], *, now: datetime | None = None,
                      scope_label: str = "") -> Worklist:
        """Bewertet beliebige Praxislisten (Ort, Region, Radius …) mit denselben deterministischen Regeln."""
        now = now or utcnow()
        customers = self.pipeline.customer_practice_ids()
        result = Worklist(scope_label, [])
        for practice in practices:
            item = self._evaluate(practice, customers, now, result)
            if item:
                result.items.append(item)
        result.items.sort(key=lambda i: (-i.score, i.practice.name.casefold(), i.practice.id or 0))
        return result

    def _evaluate(self, p: Practice, customers: set[int], now: datetime, result: Worklist) -> WorklistItem | None:
        cfg = self.scoring

        def exclude(reason: str) -> None:
            result.excluded[reason] += 1
            result.excluded_practices.append((p, reason))

        prospect = self.pipeline.get_prospect(p.id)  # type: ignore[arg-type]
        if cfg.exclude.customers and p.id in customers:
            exclude("customer")
            return None
        if prospect and prospect.stage in cfg.exclude.prospect_stages:
            exclude(f"stage_{prospect.stage.value}")
            return None
        profile = self.facts.profile(EntityType.PRACTICE, p.id, now)  # type: ignore[arg-type]
        current = {v.fact.key: v for v in profile.current}
        if cfg.exclude.already_doctolib_recognised and DOCTOLIB_SIGNAL_KEYS & current.keys():
            exclude("already_doctolib_recognised")
            return None

        reasons: list[Reason] = []
        unknowns = [f"Fact '{k}' unbekannt oder veraltet" for k in profile.unknown_keys]

        specs = [s.code for s in self.knowledge.practice_specialties(p.id)]  # type: ignore[arg-type]
        if specs:
            pts = max(cfg.specialty_fit.overrides.get(c, cfg.specialty_fit.default) for c in specs)
            reasons.append(Reason("specialty_fit", pts, f"Fachrichtung: {', '.join(specs)}"))
        else:
            unknowns.insert(0, "Fachrichtung unbekannt")

        doctors = self.knowledge.doctor_count(p.id)  # type: ignore[arg-type]
        if doctors >= 3:
            reasons.append(Reason("practice_size", cfg.practice_size.three_or_more, f"{doctors} Ärzte erfasst"))
        elif doctors == 2:
            reasons.append(Reason("practice_size", cfg.practice_size.two_doctors, "2 Ärzte erfasst"))
        elif doctors == 0:
            unknowns.append("Ärzte nicht erfasst")

        rel = self._best_referral(p.id, customers)  # type: ignore[arg-type]
        if rel:
            pts, text = rel
            reasons.append(Reason("referral_proximity", pts, text))

        signal = current.get("online_booking_signal")
        if signal:
            reasons.append(Reason("competitor_booking_signal", cfg.competitor_booking_signal,
                                  f"Andere Online-Terminbuchung erkennbar: {', '.join(signal.fact.value)}",
                                  [signal.fact.id]))  # type: ignore[list-item]

        if not profile.current and not profile.stale:
            next_action = "research_website" if p.website_url else "find_website"
        elif profile.stale:
            next_action = "refresh_research"
        else:
            next_action = "prepare_outreach"
        return WorklistItem(
            practice=p, score=sum(r.points for r in reasons), reasons=reasons, unknowns=unknowns,
            next_action=next_action, status="prospect" if prospect else "unassigned",
            stage=prospect.stage.value if prospect else None)

    def _best_referral(self, practice_id: int, customers: set[int]) -> tuple[float, str] | None:
        points = self.scoring.referral_proximity
        weight = {RelationOrigin.OBSERVED: points.observed, RelationOrigin.MANUAL: points.manual,
                  RelationOrigin.DERIVED: points.derived}
        label = {RelationOrigin.OBSERVED: "belegt", RelationOrigin.MANUAL: "manuell erfasst",
                 RelationOrigin.DERIVED: "nur regelbasiert abgeleitet, nicht belegt"}
        best = None
        for r in self.network.for_entity(EntityType.PRACTICE, practice_id, direction="in"):
            if r.rel_type is RelationType.REFERS_TO and r.from_type is EntityType.PRACTICE and r.from_id in customers:
                if best is None or weight[r.origin] > weight[best.origin]:
                    best = r
        if best is None:
            return None
        dist = (", " + format_distance(best.distance_km, best.distance_uncertainty_km or 0.0)
                if best.distance_km is not None else "")
        return weight[best.origin], f"Überweisung von Kundenpraxis #{best.from_id} ({label[best.origin]}{dist})"
