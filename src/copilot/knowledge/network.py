"""Überweisernetzwerk. Grundregel: 'derived' (Regel) wird nie als 'observed' (belegt) ausgegeben."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from copilot.config import load_yaml
from copilot.domain.enums import EntityType, FactStatus, RelationOrigin, RelationType
from copilot.domain.geo import haversine_km
from copilot.domain.models import NetworkRelationship
from copilot.errors import ConfigError, IntegrityViolation, NotFound
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.network import NetworkRepository
from copilot.storage.research import ResearchRepository


@dataclass(frozen=True)
class ReferralRules:
    version: int
    rules: dict[str, list[str]]  # source specialty code -> target codes

    @classmethod
    def load(cls, config_dir: Path) -> "ReferralRules":
        data = load_yaml(config_dir / "referral_rules.yaml") or {}
        try:
            return cls(int(data["version"]), {r["source"]: list(r["targets"]) for r in data["rules"]})
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError("referral_rules.yaml ungültig", code="config_invalid") from exc

    def rule_id(self, source: str, target: str) -> str:
        return f"referral_rules.v{self.version}:{source}->{target}"


@dataclass
class DeriveResult:
    created: int = 0
    existing: int = 0
    skipped_no_geo: int = 0
    no_specialty: bool = False


class NetworkService:
    def __init__(self, network: NetworkRepository, knowledge: KnowledgeRepository, research: ResearchRepository,
                 rules: ReferralRules):
        self.network, self.knowledge, self.research, self.rules = network, knowledge, research, rules

    def derive_for_practice(self, practice_id: int, radius_km: float = 25.0) -> DeriveResult:
        """Hausarzt -> Facharztpraxen in der Umgebung, nur regelbasiert (origin=derived)."""
        source = self.knowledge.get_practice(practice_id)
        if source is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        result = DeriveResult()
        source_specs = [s.code for s in self.knowledge.practice_specialties(practice_id)]
        applicable = sorted(
            (s, t) for s in source_specs for t in self.rules.rules.get(s, []))
        if not applicable:
            result.no_specialty = True
            return result
        targets = sorted({t for _, t in applicable})
        for cand in self.knowledge.practices_with_specialties(targets):
            if cand.id == practice_id:
                continue
            if None in (source.lat, cand.lat):
                result.skipped_no_geo += 1
                continue
            distance = haversine_km(source.lat, source.lon, cand.lat, cand.lon)  # type: ignore[arg-type]
            if distance > radius_km:
                continue
            cand_specs = {s.code for s in self.knowledge.practice_specialties(cand.id)}  # type: ignore[arg-type]
            match = next(((s, t) for s, t in applicable if t in cand_specs), None)
            if match is None:
                continue
            _, created = self.network.insert(NetworkRelationship(
                from_type=EntityType.PRACTICE, from_id=practice_id, to_type=EntityType.PRACTICE, to_id=cand.id,  # type: ignore[arg-type]
                rel_type=RelationType.REFERS_TO, origin=RelationOrigin.DERIVED,
                rule_id=self.rules.rule_id(*match), distance_km=round(distance, 1),
                note="regelbasiert abgeleitet, nicht belegt"))
            result.created += created
            result.existing += not created
        return result

    def record_observed(self, from_practice: int, to_practice: int, fact_id: int,
                        rel_type: RelationType = RelationType.REFERS_TO) -> NetworkRelationship:
        """'observed' nur mit aktivem Fact (mit Quelle), der eine der beiden Praxen betrifft."""
        fact = self.research.get_fact(fact_id)
        if fact is None:
            raise NotFound("Fact nicht gefunden", code="fact_not_found")
        if fact.status is not FactStatus.ACTIVE:
            raise IntegrityViolation("Fact ist nicht aktiv", code="fact_not_active")
        if not (fact.subject_type is EntityType.PRACTICE and fact.subject_id in (from_practice, to_practice)):
            raise IntegrityViolation("Fact gehört zu keiner der beiden Praxen", code="fact_subject_mismatch")
        rel, _ = self.network.insert(NetworkRelationship(
            from_type=EntityType.PRACTICE, from_id=from_practice, to_type=EntityType.PRACTICE, to_id=to_practice,
            rel_type=rel_type, origin=RelationOrigin.OBSERVED, fact_id=fact_id))
        return rel

    def record_manual(self, from_practice: int, to_practice: int, note: str | None = None,
                      rel_type: RelationType = RelationType.REFERS_TO) -> NetworkRelationship:
        for pid in (from_practice, to_practice):
            if self.knowledge.get_practice(pid) is None:
                raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        rel, _ = self.network.insert(NetworkRelationship(
            from_type=EntityType.PRACTICE, from_id=from_practice, to_type=EntityType.PRACTICE, to_id=to_practice,
            rel_type=rel_type, origin=RelationOrigin.MANUAL, note=note))
        return rel

    def describe(self, rel: NetworkRelationship) -> str:
        """Einziger Ausgabepfad für Herkunftslabels – 'beobachtet' erscheint ausschließlich bei origin=observed."""
        if rel.origin is RelationOrigin.OBSERVED:
            fact = self.research.get_fact(rel.fact_id)  # type: ignore[arg-type]
            source = self.research.get_source(fact.source_id) if fact else None
            where = (source.url or source.publisher or "Quelle") if source else "Quelle unbekannt"
            when = fact.observed_at.date().isoformat() if fact else "?"
            return f"BEOBACHTET (Fact #{rel.fact_id}, {where}, {when})"
        if rel.origin is RelationOrigin.DERIVED:
            return f"ABGELEITET (Regel {rel.rule_id}) – nicht belegt"
        return "MANUELL erfasst"
