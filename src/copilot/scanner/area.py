"""Gebietslogik des Territory Scanners: LocationResolver + Area-Typen.

Genauigkeit (siehe docs/TERRITORY_SCANNER.md): Praxen ohne exakte Koordinaten liegen am Ortsmittelpunkt mit
Unsicherheit ±place_uncertainty_km. Radiusprüfungen sind deshalb dreiwertig (innerhalb / möglicherweise / außerhalb);
es wird nie eine Präzision vorgetäuscht, die die Daten nicht hergeben.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from copilot.config import ScannerPolicy
from copilot.domain.geo import Certainty, GeoPoint, classify
from copilot.domain.models import Practice
from copilot.domain.territory import Place, Territory
from copilot.errors import ValidationFailed
from copilot.knowledge.network import ReferralRules
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.pipeline import PipelineRepository

_RANK = {Certainty.INSIDE: 0, Certainty.POSSIBLE: 1}


@dataclass(frozen=True)
class AreaMatch:
    certainty: Certainty
    distance_km: float | None          # Distanz der Näherungspunkte; None = nicht bestimmbar/nicht relevant
    uncertainty_km: float = 0.0
    anchor_practice_id: int | None = None   # Bezugspraxis (z. B. Kundenpraxis) bei Umkreissuchen


class Area(ABC):
    kind: str
    label: str
    radius_km: float | None
    needs_geo: bool

    @abstractmethod
    def match(self, practice: Practice, point: GeoPoint | None, specialties: set[str]) -> AreaMatch | None:
        """None = außerhalb des Gebiets."""

    def region_hint(self) -> str | None:
        """Region, auf die sich die Kandidatensuche in der DB beschränken lässt (reine Optimierung)."""
        return None

    def describe(self) -> str:
        return self.label

    def accuracy_note(self) -> str:
        return ""


@dataclass
class PlaceArea(Area):
    """'Bearbeite Saarbrücken': Praxen, deren Ort dem Ort entspricht (Zuordnung über Ortsangabe, nicht über Geodaten)."""
    territory: Territory
    place: Place
    kind: str = "place"
    needs_geo: bool = False
    radius_km: float | None = None

    @property
    def label(self) -> str:  # type: ignore[override]
        return self.place.name

    def match(self, practice, point, specialties):
        if self.territory.find_place(practice.ort) != self.place:
            return None
        center = self.territory.place_center(self.place)
        distance = point.distance_km(center) if point else None
        return AreaMatch(Certainty.INSIDE, distance, point.uncertainty_km if point else 0.0)

    def region_hint(self) -> str | None:
        return self.place.region

    def describe(self) -> str:
        return f"{self.place.name} (Ortszuordnung nach Ortsangabe)"


@dataclass
class RegionArea(Area):
    region_key: str
    region_name: str
    kind: str = "region"
    needs_geo: bool = False
    radius_km: float | None = None

    @property
    def label(self) -> str:  # type: ignore[override]
        return self.region_name

    def match(self, practice, point, specialties):
        return AreaMatch(Certainty.INSIDE, None) if practice.region == self.region_key else None

    def region_hint(self) -> str | None:
        return self.region_key

    def describe(self) -> str:
        return f"Region {self.region_name} (Zuordnung nach Region)"


@dataclass
class RadiusArea(Area):
    """'10 km um Saarbrücken' bzw. '5 km um Praxis X'."""
    center: GeoPoint
    radius_km: float  # type: ignore[assignment]
    center_label: str
    exclude_practice_id: int | None = None
    kind: str = "radius"
    needs_geo: bool = True

    @property
    def label(self) -> str:  # type: ignore[override]
        return f"{self.radius_km:g} km um {self.center_label}"

    def match(self, practice, point, specialties):
        if point is None or (self.exclude_practice_id is not None and practice.id == self.exclude_practice_id):
            return None
        certainty, distance, uncertainty = classify(self.center, point, self.radius_km)
        return None if certainty is Certainty.OUTSIDE else AreaMatch(certainty, distance, uncertainty)

    def accuracy_note(self) -> str:
        c = "exakter Standort" if self.center.precision == "exact" else (
            "Ortsmittelpunkt (per Definition)" if self.center.precision == "definition"
            else f"Praxisposition nur ≈ (±{self.center.uncertainty_km:g} km)")
        return f"Suchzentrum: {c}"


@dataclass
class Anchor:
    practice: Practice
    point: GeoPoint
    targets: frozenset[str]   # Fachrichtungen, die laut Überweiser-Regeln von dieser Praxis aus relevant sind


@dataclass
class CustomerRadiusArea(Area):
    """'Relevante Fachärzte im Umfeld meiner Hausarztkunden': Umkreis um jede Kundenpraxis, begrenzt auf die
    laut Regeln relevanten Fachrichtungen dieser Kundenpraxis (Heuristik, keine belegte Beziehung)."""
    anchors: list[Anchor]
    radius_km: float  # type: ignore[assignment]
    scope_label: str
    skipped_anchors_no_geo: int = 0
    kind: str = "customers"
    needs_geo: bool = True

    @property
    def label(self) -> str:  # type: ignore[override]
        n = len(self.anchors)
        return f"{self.radius_km:g} km um {n} {'Kundenpraxis' if n == 1 else 'Kundenpraxen'} ({self.scope_label})"

    def match(self, practice, point, specialties):
        if point is None:
            return None
        best: tuple[tuple[int, float], AreaMatch] | None = None
        for a in self.anchors:
            if a.practice.id == practice.id or not (a.targets & specialties):
                continue
            certainty, distance, uncertainty = classify(a.point, point, self.radius_km)
            if certainty is Certainty.OUTSIDE:
                continue
            rank = (_RANK[certainty], distance)
            if best is None or rank < best[0]:
                best = (rank, AreaMatch(certainty, distance, uncertainty, a.practice.id))
        return best[1] if best else None

    def accuracy_note(self) -> str:
        skipped = f"; {self.skipped_anchors_no_geo} Kundenpraxen ohne Geodaten übersprungen" if self.skipped_anchors_no_geo else ""
        return "Bezugspunkte: Kundenpraxen (Position ggf. nur Ortsmittelpunkt)" + skipped


@dataclass
class AreaRequest:
    scope: str | None = None
    radius_km: float | None = None
    around_practice: int | None = None
    around_customers: bool = False
    specialty_codes: frozenset[str] = field(default_factory=frozenset)


class LocationResolver:
    def __init__(self, territory: Territory, knowledge: KnowledgeRepository, pipeline: PipelineRepository,
                 rules: ReferralRules, policy: ScannerPolicy):
        self.territory, self.knowledge, self.pipeline = territory, knowledge, pipeline
        self.rules, self.policy = rules, policy

    def resolve(self, req: AreaRequest) -> Area:
        radius = req.radius_km
        if radius is not None and not 0 < radius <= self.policy.max_radius_km:
            raise ValidationFailed(f"Radius muss zwischen 0 und {self.policy.max_radius_km:g} km liegen",
                                   code="radius_out_of_range")
        if req.around_practice is not None:
            return self._around_practice(req.around_practice, radius or self.policy.default_radius_km)
        scope = self.territory.parse_scope(req.scope) if req.scope else None
        if req.scope and scope is None:
            known = sorted({p.name for p in self.territory.places} | {r.name for r in self.territory.regions.values()})
            raise ValidationFailed(f"Unbekanntes Gebiet '{req.scope}'. Bekannt: {', '.join(known)}", code="unknown_scope")
        if req.around_customers:
            return self._around_customers(scope, radius or self.policy.default_radius_km, req.specialty_codes)
        if scope is None:
            raise ValidationFailed("Gebiet angeben (z. B. 'Saarbrücken') oder --around-practice/--around-customers nutzen",
                                   code="scope_required")
        if scope.kind == "region":
            if radius is not None:
                raise ValidationFailed("Radius ist nur für Orte oder Praxen möglich, nicht für ganze Regionen",
                                       code="radius_needs_place")
            return RegionArea(scope.region.key, scope.region.name)  # type: ignore[union-attr]
        if radius is None:
            return PlaceArea(self.territory, scope.place)  # type: ignore[arg-type]
        return RadiusArea(self.territory.place_center(scope.place), radius, scope.place.name)  # type: ignore[arg-type]

    def _around_practice(self, practice_id: int, radius: float) -> Area:
        practice = self.knowledge.get_practice(practice_id)
        if practice is None:
            raise ValidationFailed(f"Praxis {practice_id} nicht gefunden", code="practice_not_found")
        point = self.territory.point_for(practice)
        if point is None:
            raise ValidationFailed("Für diese Praxis liegen keine Geodaten vor – kein Umkreis möglich", code="center_without_geo")
        return RadiusArea(point, radius, f"Praxis #{practice_id}", exclude_practice_id=practice_id)

    def _around_customers(self, scope, radius: float, only: frozenset[str]) -> Area:
        anchors, skipped = [], 0
        for pid in sorted(self.pipeline.customer_practice_ids()):
            practice = self.knowledge.get_practice(pid)
            if practice is None or not self._in_scope(practice, scope):
                continue
            targets = {t for s in self.knowledge.practice_specialties(pid) for t in self.rules.rules.get(s.code, [])}
            if only:
                targets &= only
            if not targets:
                continue
            point = self.territory.point_for(practice)
            if point is None:
                skipped += 1
                continue
            anchors.append(Anchor(practice, point, frozenset(targets)))
        if not anchors:
            raise ValidationFailed(
                "Keine Kundenpraxen mit anwendbaren Überweiser-Regeln und Geodaten im Gebiet gefunden "
                "(Kunden importieren: copilot import practices DATEI --as customers)", code="no_customer_anchors")
        return CustomerRadiusArea(anchors, radius, scope.label if scope else "gesamtes Gebiet", skipped)

    def _in_scope(self, practice: Practice, scope) -> bool:
        if scope is None:
            return practice.region is not None
        if scope.kind == "place":
            return self.territory.find_place(practice.ort) == scope.place
        return practice.region == scope.region.key
