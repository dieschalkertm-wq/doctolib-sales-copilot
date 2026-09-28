"""Knowledge-Service: Practice/Doctor/Specialty-Stammdaten (dauerhaft, ohne Rechercheergebnisse)."""

from __future__ import annotations

from dataclasses import dataclass, field

from copilot.domain.enums import GeoPrecision
from copilot.domain.models import Doctor, Practice
from copilot.domain.normalize import doctor_key, fold, practice_key
from copilot.errors import NotFound
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

    def build_candidate(self, rec: PracticeRecord) -> tuple[Practice, list[str]]:
        warnings: list[str] = []
        resolution = self.territory.resolve(rec.ort, rec.plz)
        if not rec.ort and not rec.plz:
            warnings.append("missing_location")
        elif resolution.region is None:
            warnings.append("outside_territory")
        geo: dict = {}
        if rec.lat is not None:  # exakte Koordinaten aus der Quelle schlagen den Ortsmittelpunkt
            geo = {"lat": rec.lat, "lon": rec.lon, "geo_precision": GeoPrecision.EXACT}
        elif resolution.place:
            geo = {"lat": resolution.place.lat, "lon": resolution.place.lon, "geo_precision": GeoPrecision.PLACE}
        candidate = Practice(
            name=rec.name, street=rec.street, plz=rec.plz, ort=rec.ort, ort_key=fold(rec.ort) or None,
            region=resolution.region, website_url=rec.website,
            canonical_key=practice_key(rec.name, rec.plz, rec.street), **geo)
        return candidate, warnings

    def upsert_practice(self, rec: PracticeRecord) -> UpsertResult:
        candidate, warnings = self.build_candidate(rec)
        existing = self.repo.find_practice_by_key(candidate.canonical_key)
        return self._apply(existing, candidate, rec, warnings)

    def attach_to_existing(self, practice_id: int, rec: PracticeRecord) -> UpsertResult:
        """Kandidat gehört (per Matcher oder Nutzerentscheidung) zu einer bestehenden Praxis: nur Lücken füllen."""
        candidate, warnings = self.build_candidate(rec)
        existing = self.repo.get_practice(practice_id)
        if existing is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        return self._apply(existing, candidate, rec, warnings)

    def _apply(self, existing: Practice | None, candidate: Practice, rec: PracticeRecord,
               warnings: list[str]) -> UpsertResult:
        if existing is None:
            practice, status = self.repo.insert_practice(candidate), "created"
        else:
            # Import füllt nur Lücken; bestehende Werte werden nicht überschrieben (kein Hin-und-Her bei Schreibvarianten).
            fill = {f: getattr(candidate, f) for f in ("street", "plz", "ort", "ort_key", "region", "website_url")
                    if getattr(existing, f) is None and getattr(candidate, f) is not None}
            better_geo = candidate.lat is not None and (
                existing.lat is None or (candidate.geo_precision is GeoPrecision.EXACT
                                         and existing.geo_precision is not GeoPrecision.EXACT))
            if better_geo:  # Genauigkeit darf nur steigen: exakt schlägt Ortsmittelpunkt
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

    def set_exact_location(self, practice_id: int, lat: float, lon: float) -> Practice:
        """Für spätere Geocoder/manuelle Korrektur: hebt eine Praxis von 'Ortsmittelpunkt' auf 'exakt'."""
        practice = self.repo.get_practice(practice_id)
        if practice is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        updated = Practice.model_validate({**practice.model_dump(), "lat": lat, "lon": lon,
                                           "geo_precision": GeoPrecision.EXACT})
        return self.repo.update_practice(updated)

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
