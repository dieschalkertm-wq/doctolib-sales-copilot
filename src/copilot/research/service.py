"""ResearchService: führt einen Provider aus und persistiert Research, Source und Facts (mit Provenance)."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from copilot.domain.enums import EntityType, ResearchStatus
from copilot.domain.models import Fact, Research, Source
from copilot.domain.timeutil import utcnow
from copilot.errors import FetchError, NotFound, PolicyViolation
from copilot.research.facts import FactService
from copilot.research.provider import ProviderOutput, ResearchProvider, ResearchRequest
from copilot.storage.audit import AuditLog
from copilot.storage.db import transaction
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.research import ResearchRepository


@dataclass
class RunResult:
    research_id: int
    source: Source
    facts: list[Fact] = field(default_factory=list)


class ResearchService:
    def __init__(self, conn: sqlite3.Connection, repo: ResearchRepository, facts: FactService,
                 knowledge: KnowledgeRepository, audit: AuditLog, raw_cache_dir: Path):
        self.conn, self.repo, self.facts, self.knowledge = conn, repo, facts, knowledge
        self.audit, self.raw_cache_dir = audit, raw_cache_dir

    def run(self, provider: ResearchProvider, request: ResearchRequest) -> RunResult:
        if request.subject_type is EntityType.PRACTICE and self.knowledge.get_practice(request.subject_id) is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        with transaction(self.conn):
            research = self.repo.start_research(Research(
                subject_type=request.subject_type, subject_id=request.subject_id, kind=provider.kind,
                provider=provider.name, started_at=utcnow()))
        try:
            output = provider.collect(request)
        except (PolicyViolation, FetchError) as exc:
            status = ResearchStatus.BLOCKED if isinstance(exc, PolicyViolation) else ResearchStatus.FAILED
            self._finish_failed(provider, research.id, status, exc.code)  # type: ignore[arg-type]
            raise
        return self._store(provider.name, request, research.id, output)  # type: ignore[arg-type]

    def persist_output(self, provider_name: str, kind: str, request: ResearchRequest, output: ProviderOutput) -> RunResult:
        """Persistiert das Ergebnis eines Providers, der bereits außerhalb gelaufen ist (z. B. Scanner-Kandidat mit
        belegten Facts). Gleicher Provenance-Pfad wie run(): Research + Source + Facts + Audit."""
        with transaction(self.conn):
            research = self.repo.start_research(Research(
                subject_type=request.subject_type, subject_id=request.subject_id, kind=kind,
                provider=provider_name, started_at=utcnow()))
            return self._store(provider_name, request, research.id, output)  # type: ignore[arg-type]

    def _store(self, provider_name: str, request: ResearchRequest, research_id: int, output: ProviderOutput) -> RunResult:
        with transaction(self.conn):
            draft = output.source
            source = self.repo.insert_source(Source(
                source_type=draft.source_type, url=draft.url, publisher=draft.publisher, retrieved_at=utcnow(),
                published_at=draft.published_at, content_hash=draft.content_hash, robots_status=draft.robots_status,
                tos_ref=draft.tos_ref, reliability=draft.reliability,
                raw_ref=self._cache_raw(draft.content_hash, draft.raw_content)))
            facts = [self.facts.record(request.subject_type, request.subject_id, d, source.id,  # type: ignore[arg-type]
                                       research_id=research_id, observed_at=source.retrieved_at)
                     for d in output.facts]
            self.repo.finish_research(research_id, ResearchStatus.SUCCEEDED, utcnow())
            self.audit.record("research.run", "Research abgeschlossen", entity_type=request.subject_type.value,
                              entity_id=request.subject_id, content_hash=draft.content_hash,
                              details={"provider": provider_name, "status": "succeeded", "source_id": source.id,
                                       "research_id": research_id, "fact_count": len(facts)})
        return RunResult(research_id, source, facts)

    def _finish_failed(self, provider: ResearchProvider, research_id: int, status: ResearchStatus, code: str) -> None:
        with transaction(self.conn):
            self.repo.finish_research(research_id, status, utcnow(), code)
            self.audit.record("research.run", "Research nicht ausgeführt", details={
                "provider": provider.name, "status": status.value, "error_code": code, "research_id": research_id})

    def _cache_raw(self, content_hash: str | None, content: bytes | None) -> str | None:
        """Rohinhalt bleibt lokal (data/raw_cache, gitignored, 0600) – Grundlage zum Nachprüfen der Facts."""
        if not content or not content_hash:
            return None
        if not self.raw_cache_dir.exists():
            self.raw_cache_dir.mkdir(parents=True)
            os.chmod(self.raw_cache_dir, 0o700)
        path = self.raw_cache_dir / f"{content_hash}.html"
        if not path.exists():
            path.write_bytes(content)
            os.chmod(path, 0o600)
        return path.name
