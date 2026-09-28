"""Nimmt Provider-Kandidaten in den Bestand auf: Gebiets-/Fachrichtungsfilter -> Matcher -> anhängen | Queue | neu.

Es entsteht nie ungeprüftes Fuzzy-Merging: nur EXACT wird angehängt (und dabei nur Lücken gefüllt),
POSSIBLE landet in der Merge-Queue, NONE wird als neue Praxis angelegt."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from copilot.domain.enums import EntityType
from copilot.domain.territory import Territory
from copilot.knowledge.service import KnowledgeService
from copilot.knowledge.specialties import SpecialtyCatalog
from copilot.research.provider import ProviderOutput, ResearchRequest
from copilot.research.service import ResearchService
from copilot.scanner.area import Area
from copilot.scanner.matcher import ExistingDataMatcher, MatchKind
from copilot.scanner.providers.base import Candidate
from copilot.storage.merge import MergeRepository


@dataclass
class QueuedItem:
    merge_id: int
    candidate_name: str
    practice_id: int
    confidence: float
    reasons: list[str]
    new: bool          # False = war bereits eingereiht


@dataclass
class IngestReport:
    seen: int = 0
    created: int = 0
    attached: int = 0
    queued: int = 0
    already_queued: int = 0
    skipped_outside: int = 0
    skipped_no_geo: int = 0
    skipped_specialty: int = 0
    created_ids: list[int] = field(default_factory=list)
    attached_ids: list[int] = field(default_factory=list)
    queue: list[QueuedItem] = field(default_factory=list)


class CandidateIngestor:
    def __init__(self, knowledge: KnowledgeService, matcher: ExistingDataMatcher, merge: MergeRepository,
                 research: ResearchService, territory: Territory, catalog: SpecialtyCatalog):
        self.knowledge, self.matcher, self.merge = knowledge, matcher, merge
        self.research, self.territory, self.catalog = research, territory, catalog

    def ingest(self, candidates: Iterable[Candidate], area: Area, specialty_filter: frozenset[str]) -> IngestReport:
        report = IngestReport()
        for cand in candidates:
            report.seen += 1
            rec = cand.record
            preview, _ = self.knowledge.build_candidate(rec)
            codes = {c for label in rec.specialty_labels if (c := self.catalog.resolve(label))}
            if specialty_filter and not (codes & specialty_filter):
                report.skipped_specialty += 1
                continue
            point = self.territory.point_for(preview)
            if area.needs_geo and point is None:
                report.skipped_no_geo += 1
                continue
            if area.match(preview, point, codes) is None:
                report.skipped_outside += 1
                continue

            match = self.matcher.match(rec, cand.provider)
            if match.kind is MatchKind.EXACT:
                result = self.knowledge.attach_to_existing(match.practice_id, rec)  # type: ignore[arg-type]
                report.attached += 1
                report.attached_ids.append(result.practice.id)  # type: ignore[arg-type]
                self.matcher.add_doctors(result.practice.id, rec.doctors)  # type: ignore[arg-type]
                self._finish(cand, result.practice.id)  # type: ignore[arg-type]
            elif match.kind is MatchKind.POSSIBLE:
                new_any = False
                for pid, confidence, reasons in match.candidates:
                    merge_id, new = self.merge.enqueue(pid, preview.canonical_key, cand.provider, cand.source_ref,
                                                       rec, confidence, reasons)
                    new_any |= new
                    report.queue.append(QueuedItem(merge_id, rec.name, pid, confidence, reasons, new))
                report.queued += new_any
                report.already_queued += not new_any
            else:
                result = self.knowledge.upsert_practice(rec)
                self.matcher.add(result.practice)
                self.matcher.add_doctors(result.practice.id, rec.doctors)  # type: ignore[arg-type]
                report.created += 1
                report.created_ids.append(result.practice.id)  # type: ignore[arg-type]
                self._finish(cand, result.practice.id)  # type: ignore[arg-type]
        return report

    def _finish(self, cand: Candidate, practice_id: int) -> None:
        self.knowledge.repo.record_origin(practice_id, cand.provider, cand.source_ref)
        if cand.source is not None and cand.facts:   # belegbare Facts des Providers: gleicher Provenance-Pfad wie Research
            self.research.persist_output(
                cand.provider, "source_discovery", ResearchRequest(EntityType.PRACTICE, practice_id, cand.source.url),
                ProviderOutput(source=cand.source, facts=cand.facts))
