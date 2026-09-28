"""Knowledge-Service: Practice/Doctor/Specialty-Stammdaten (dauerhaft, ohne Rechercheergebnisse)."""

from __future__ import annotations

from dataclasses import dataclass, field

from copilot.domain.enums import GeoPrecision
from copilot.domain.models import Doctor, Practice
from copilot.domain.normalize import doctor_key, fold, practice_key
from copilot.domain.territory import Territory
from copilot.knowledge.records import PracticeRecord
from copilot.knowledge.specialties import SpecialtyCatalog
from copilot.storage.knowledge import KnowledgeRepository


@dataclass
class UpsertResult:
    practice: Practice
    status: str  # created | updated | unchanged
    warnings: list[str] = field(default_factory=list)


class KnowledgeService:
    def __init__(self, repo: KnowledgeRepository, territory: Territory, catalog: SpecialtyCatalog):
        self.repo, self.territory, self.catalog = repo, territory, catalog

    def upsert_practice(self, rec: PracticeRecord) -> UpsertResult:
        warnings: list[str] = []
        resolution = self.territory.resolve(rec.ort, rec.plz)
        if not rec.ort and not rec.plz:
            warnings.append("missing_location")
        elif resolution.region is None:
            warnings.append("outside_territory")

        candidate = Practice(
            name=rec.name, street=rec.street, plz=rec.plz, ort=rec.ort, ort_key=fold(rec.ort) or None,
            region=resolution.region, website_url=rec.website,
            canonical_key=practice_key(rec.name, rec.plz, rec.street),
            **({"lat": resolution.place.lat, "lon": resolution.place.lon, "geo_precision": GeoPrecision.PLACE}
               if resolution.place else {}),
        )
        existing = self.repo.find_practice_by_key(candidate.canonical_key)
        if existing is None:
            practice, status = self.repo.insert_practice(candidate), "created"
        else:
            # Import füllt nur Lücken; bestehende Werte werden nicht überschrieben (kein Hin-und-Her bei Schreibvarianten).
            fill = {f: getattr(candidate, f) for f in ("street", "plz", "ort", "ort_key", "region", "website_url")
                    if getattr(existing, f) is None and getattr(candidate, f) is not None}
            if existing.lat is None and candidate.lat is not None:
                fill.update(lat=candidate.lat, lon=candidate.lon, geo_precision=candidate.geo_precision)
            merged = existing.model_copy(update=fill)
            changed = merged != existing
            practice = self.repo.update_practice(merged) if changed else existing
            status = "updated" if changed else "unchanged"

        changed_links = self._attach_specialties(practice.id, rec, warnings)  # type: ignore[arg-type]
        changed_links |= self._attach_doctors(practice.id, rec)  # type: ignore[arg-type]
        if status == "unchanged" and changed_links:
            status = "updated"
        return UpsertResult(practice, status, warnings)

    def _attach_specialties(self, practice_id: int, rec: PracticeRecord, warnings: list[str]) -> bool:
        changed = False
        for label in rec.specialty_labels:
            code = self.catalog.resolve(label)
            spec = self.repo.get_specialty_by_code(code) if code else None
            if spec is None:
                warnings.append("unknown_specialty")
                continue
            changed |= self.repo.add_practice_specialty(practice_id, spec.id)  # type: ignore[arg-type]
        return changed

    def _attach_doctors(self, practice_id: int, rec: PracticeRecord) -> bool:
        changed = False
        for d in rec.doctors:
            key = doctor_key(d.full_name)
            if key and self.repo.find_doctor_of_practice(practice_id, key) is None:
                self.repo.insert_doctor(Doctor(full_name=d.full_name, title=d.title, canonical_key=key), practice_id)
                changed = True
        return changed
