"""Ergebnis-Modelle des Territory Scans (UI-unabhängig; `to_dict()` ist die Basis für eine spätere Web-UI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from copilot.domain.models import Practice
from copilot.pipeline.worklist import NEXT_ACTIONS, WorklistItem
from copilot.scanner.area import AreaMatch
from copilot.scanner.ingest import IngestReport


@dataclass
class ScanItem:
    practice: Practice
    specialties: list[str]
    doctors: list[str]
    match: AreaMatch | None
    distance: str                 # bereits formatiert, inkl. Unsicherheit
    origins: list[str]
    status: str                   # unassigned | prospect
    stage: str | None
    research_status: str
    doctolib_signal: str
    website: str | None
    facts: list[str]
    network: list[str]
    worklist: WorklistItem
    is_new: bool = False

    @property
    def next_action_text(self) -> str:
        return NEXT_ACTIONS.get(self.worklist.next_action, self.worklist.next_action)

    def to_dict(self) -> dict[str, Any]:
        p = self.practice
        return {
            "practice_id": p.id, "name": p.name, "street": p.street, "plz": p.plz, "ort": p.ort, "region": p.region,
            "geo_precision": p.geo_precision.value if p.geo_precision else None,
            "specialties": self.specialties, "doctors": self.doctors,
            "distance": {"text": self.distance,
                         "km": self.match.distance_km if self.match else None,
                         "uncertainty_km": self.match.uncertainty_km if self.match else None,
                         "certainty": self.match.certainty.value if self.match else None,
                         "anchor_practice_id": self.match.anchor_practice_id if self.match else None},
            "origins": self.origins, "status": self.status, "stage": self.stage,
            "research_status": self.research_status, "doctolib_signal": self.doctolib_signal,
            "website": self.website, "facts": self.facts, "network": self.network, "is_new": self.is_new,
            "score": self.worklist.score,
            "reasons": [{"criterion": r.criterion, "points": r.points, "explanation": r.explanation,
                         "fact_ids": r.fact_ids} for r in self.worklist.reasons],
            "unknowns": self.worklist.unknowns,
            "next_action": {"code": self.worklist.next_action, "text": self.next_action_text},
        }


@dataclass
class ResearchOutcome:
    practice_id: int
    status: str        # researched | blocked | failed
    detail: str        # Fehler-/Policy-Code oder Anzahl Facts
    fact_count: int = 0


@dataclass
class NetworkSummary:
    created: int = 0
    existing: int = 0
    skipped_no_geo: int = 0


@dataclass
class ScanResult:
    area_label: str
    area_description: str
    accuracy_notes: list[str]
    dry_run: bool
    items: list[ScanItem] = field(default_factory=list)
    excluded: list[tuple[Practice, str]] = field(default_factory=list)
    ingest: list[tuple[str, IngestReport, list[tuple[int, list[str]]]]] = field(default_factory=list)  # (Provider, Bericht, Zeilenfehler)
    research: list[ResearchOutcome] = field(default_factory=list)
    research_pending: int = 0      # Praxen, die noch recherchiert werden könnten (ohne --research)
    network: NetworkSummary = field(default_factory=NetworkSummary)
    no_geo: int = 0                # Praxen im Gebiet, deren Position für Radiusprüfungen fehlt
    dropped_uncertain: int = 0     # bei --strict-radius verworfene „möglicherweise innerhalb“
    skipped_specialty: int = 0
    open_merge_candidates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "area": {"label": self.area_label, "description": self.area_description, "accuracy": self.accuracy_notes},
            "dry_run": self.dry_run,
            "items": [i.to_dict() for i in self.items],
            "excluded": [{"practice_id": p.id, "reason": r} for p, r in self.excluded],
            "providers": [{"provider": n, "seen": r.seen, "created": r.created, "attached": r.attached,
                           "queued": r.queued, "skipped_outside": r.skipped_outside,
                           "skipped_no_geo": r.skipped_no_geo, "skipped_specialty": r.skipped_specialty,
                           "rejected_rows": [{"row": row, "codes": codes} for row, codes in rej]}
                          for n, r, rej in self.ingest],
            "research": [o.__dict__ for o in self.research],
            "network": self.network.__dict__,
            "no_geo": self.no_geo, "dropped_uncertain": self.dropped_uncertain,
            "open_merge_candidates": self.open_merge_candidates,
        }
