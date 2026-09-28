"""TerritoryScanner: „Bearbeite Saarbrücken.“ -> Arbeitsliste.

Ablauf (jeder Schritt ist ein eigener, austauschbarer Baustein):
  LocationResolver -> SourceProvider(s) -> ExistingDataMatcher/Ingest -> Gebietsmitglieder -> Worklist-Bewertung
  -> ResearchEngine (optional) -> NetworkAnalyzer -> ProspectListBuilder
Alle Schreibvorgänge laufen in EINER Transaktion; `dry_run` rollt am Ende zurück (Vorschau ohne Nebenwirkung).
Level 1/2: es gibt keine externen Aktionen (keine Mails, keine LinkedIn-Nachrichten, keine CRM-Änderungen)."""

from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from copilot.config import Policies
from copilot.connectors.imports.mapping import load_mapping
from copilot.domain.geo import Certainty
from copilot.domain.models import Practice
from copilot.domain.territory import Territory
from copilot.domain.timeutil import utcnow
from copilot.errors import ValidationFailed
from copilot.knowledge.specialties import SpecialtyCatalog
from copilot.pipeline.worklist import Worklist, WorklistService
from copilot.scanner.area import Area, AreaMatch, AreaRequest, LocationResolver
from copilot.scanner.builder import ProspectListBuilder
from copilot.scanner.ingest import CandidateIngestor
from copilot.scanner.matcher import ExistingDataMatcher
from copilot.scanner.network import NetworkAnalyzer
from copilot.scanner.providers.base import DiscoveryQuery, SourceProvider
from copilot.scanner.providers.doctolib import DoctolibAccessMethod, DoctolibProvider
from copilot.scanner.providers.local_import import LocalImportProvider
from copilot.scanner.providers.map import MapProvider
from copilot.scanner.research import ResearchEngine
from copilot.scanner.result import ScanResult
from copilot.storage.audit import AuditLog
from copilot.storage.db import transaction
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.merge import MergeRepository

WORKED_STAGES = {"contacted", "meeting", "proposal"}


@dataclass
class ScanRequest:
    scope: str | None = None
    radius_km: float | None = None
    around_practice: int | None = None
    around_customers: bool = False
    specialties: list[str] = field(default_factory=list)
    from_files: list[Path] = field(default_factory=list)
    mapping: Path | None = None
    providers: list[str] = field(default_factory=list)      # vorbereitete Provider: doctolib, map
    unworked: bool = False
    strict_radius: bool = False
    research: bool = False
    research_limit: int = 10
    limit: int | None = None
    dry_run: bool = False


class _DryRun(Exception):
    pass


class TerritoryScanner:
    def __init__(self, *, conn: sqlite3.Connection, territory: Territory, catalog: SpecialtyCatalog, policies: Policies,
                 knowledge: KnowledgeRepository, merge: MergeRepository, resolver: LocationResolver,
                 matcher: ExistingDataMatcher, ingestor: CandidateIngestor, worklist: WorklistService,
                 builder: ProspectListBuilder, network: NetworkAnalyzer, research: ResearchEngine, audit: AuditLog):
        self.conn, self.territory, self.catalog, self.policies = conn, territory, catalog, policies
        self.knowledge, self.merge, self.resolver, self.matcher = knowledge, merge, resolver, matcher
        self.ingestor, self.worklist, self.builder = ingestor, worklist, builder
        self.network, self.research, self.audit = network, research, audit
        self.doctolib_access_method: DoctolibAccessMethod | None = None   # Einhängepunkt für eine spätere Zugriffsmethode

    # ------------------------------------------------------------------ öffentliche API
    def scan(self, req: ScanRequest) -> ScanResult:
        specialty_filter = self._specialty_codes(req.specialties)
        area = self.resolver.resolve(AreaRequest(req.scope, req.radius_km, req.around_practice,
                                                 req.around_customers, specialty_filter))
        providers = self._providers(req)
        for provider in providers:
            provider.ensure_ready()            # nicht freigegeben/nicht implementiert -> klarer Fehler VOR jeder Arbeit

        result = ScanResult(area.label, area.describe(), self._accuracy_notes(area), req.dry_run)
        try:
            with transaction(self.conn):
                self._run(req, area, specialty_filter, providers, result)
                if req.dry_run:
                    raise _DryRun
        except _DryRun:
            pass
        return result

    # ------------------------------------------------------------------ Ablauf
    def _run(self, req: ScanRequest, area: Area, spec_filter: frozenset[str], providers: list[SourceProvider],
             result: ScanResult) -> None:
        now = utcnow()
        self.matcher.load()
        new_ids: set[int] = set()
        for provider in providers:
            report = self.ingestor.ingest(provider.discover(DiscoveryQuery(area, spec_filter)), area, spec_filter)
            rejected = list(getattr(provider, "rejected", []))
            result.ingest.append((provider.name, report, rejected))
            new_ids |= set(report.created_ids)

        members = self._members(area, spec_filter, req, result)
        practices = [p for p, _ in members]
        matches: dict[int, AreaMatch] = {p.id: m for p, m in members}  # type: ignore[misc]

        # Netzwerkbezüge VOR der Bewertung ableiten, damit sie (als 'derived') in den Score einfließen
        radius = area.radius_km or self.policies.scanner.network_radius_km
        result.network = self.network.analyze({p.id for p in practices}, radius)  # type: ignore[misc]

        wl = self._evaluate(practices, now, req)
        if req.research and not req.dry_run:
            result.research = self.research.run(wl.items, req.research_limit)
            if any(o.status in ("researched", "failed") for o in result.research):
                wl = self._evaluate(practices, utcnow(), req)      # neue Facts fließen in die Bewertung ein
        result.research_pending = len(self.research.pending(wl.items))

        items = [self.builder.build_item(i.practice, matches.get(i.practice.id), i, now, new_ids)  # type: ignore[arg-type]
                 for i in wl.items]
        items.sort(key=lambda s: (-s.worklist.score,
                                  s.match.distance_km if s.match and s.match.distance_km is not None else 1e9,
                                  s.practice.name.casefold(), s.practice.id or 0))
        result.items = items[:req.limit] if req.limit else items
        result.excluded = wl.excluded_practices
        result.open_merge_candidates = len(self.merge.list("open"))
        if not req.dry_run:
            created = sum(r.created for _, r, _ in result.ingest)
            self.audit.record("territory.scan", "Territory Scan ausgeführt", details={
                "scope": area.kind, "radius_km": area.radius_km or 0, "candidates": sum(r.seen for _, r, _ in result.ingest),
                "created": created, "attached": sum(r.attached for _, r, _ in result.ingest),
                "queued": sum(r.queued for _, r, _ in result.ingest), "count": len(result.items)})

    def _members(self, area: Area, spec_filter: frozenset[str], req: ScanRequest,
                 result: ScanResult) -> list[tuple[Practice, AreaMatch]]:
        region = area.region_hint()
        pool = self.knowledge.list_practices(region=region) if region else self.knowledge.list_practices()
        members: list[tuple[Practice, AreaMatch]] = []
        for practice in pool:
            codes = {s.code for s in self.knowledge.practice_specialties(practice.id)}  # type: ignore[arg-type]
            point = self.territory.point_for(practice)
            if area.needs_geo and point is None:
                result.no_geo += practice.region is not None      # nur Praxen im Vertriebsgebiet zählen
                continue
            match = area.match(practice, point, codes)
            if match is None:
                continue
            if spec_filter and not (codes & spec_filter):
                result.skipped_specialty += 1
                continue
            if req.strict_radius and match.certainty is Certainty.POSSIBLE:
                result.dropped_uncertain += 1
                continue
            members.append((practice, match))
        return members

    def _evaluate(self, practices: list[Practice], now, req: ScanRequest) -> Worklist:
        wl = self.worklist.evaluate_many(practices, now=now)
        if req.unworked:
            kept = []
            for item in wl.items:
                if item.stage in WORKED_STAGES:
                    wl.excluded["already_worked"] += 1
                    wl.excluded_practices.append((item.practice, "already_worked"))
                else:
                    kept.append(item)
            wl.items = kept
        return wl

    # ------------------------------------------------------------------ Hilfen
    def _specialty_codes(self, labels: list[str]) -> frozenset[str]:
        codes = set()
        for label in labels:
            code = self.catalog.resolve(label)
            if code is None:
                raise ValidationFailed(f"Unbekannte Fachrichtung '{label}' (copilot specialties zeigt den Katalog)",
                                       code="unknown_specialty")
            codes.add(code)
        return frozenset(codes)

    def _providers(self, req: ScanRequest) -> list[SourceProvider]:
        cfg = self.policies.providers
        providers: list[SourceProvider] = []
        mapping = load_mapping(req.mapping)
        for path in req.from_files:
            providers.append(LocalImportProvider(cfg.local_import, path, mapping))
        for name in req.providers:
            if name == "doctolib":
                providers.append(DoctolibProvider(cfg.doctolib, self.doctolib_access_method))
            elif name == "map":
                providers.append(MapProvider(cfg.map))
            else:
                raise ValidationFailed(f"Unbekannter Provider '{name}' (erlaubt: doctolib, map; Dateien via --from-file)",
                                       code="unknown_provider")
        return providers

    def _accuracy_notes(self, area: Area) -> list[str]:
        notes = []
        if area.needs_geo:
            notes.append(
                f"Praxen ohne exakte Koordinaten liegen am Ortsmittelpunkt (Unsicherheit ±"
                f"{self.territory.default_place_uncertainty_km:g} km, je Ort konfigurierbar). "
                "Entfernungen dazu sind Näherungen; 'möglicherweise' heißt: je nach tatsächlichem Standort drinnen oder draußen.")
        else:
            notes.append("Zuordnung nach Ortsangabe; Entfernungen (falls angezeigt) sind Näherungen zum Ortsmittelpunkt.")
        if extra := area.accuracy_note():
            notes.append(extra)
        return notes
