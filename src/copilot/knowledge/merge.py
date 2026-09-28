"""Merge-Queue-Entscheidungen. Zusammengeführt wird ausschließlich nach ausdrücklicher Nutzerentscheidung."""

from __future__ import annotations

from dataclasses import dataclass

from copilot.errors import IntegrityViolation, NotFound, ValidationFailed
from copilot.knowledge.service import KnowledgeService
from copilot.storage.audit import AuditLog
from copilot.storage.db import transaction
from copilot.storage.merge import MergeRepository


@dataclass
class ResolveResult:
    decision: str
    practice_id: int | None      # Praxis, an die angehängt wurde, bzw. neu angelegte Praxis
    created: bool = False


class MergeService:
    def __init__(self, repo: MergeRepository, knowledge: KnowledgeService, audit: AuditLog, conn):
        self.repo, self.knowledge, self.audit, self.conn = repo, knowledge, audit, conn

    def resolve(self, merge_id: int, decision: str) -> ResolveResult:
        if decision not in ("same", "different"):
            raise ValidationFailed("decision muss 'same' oder 'different' sein", code="invalid_decision")
        cand = self.repo.get(merge_id)
        if cand is None:
            raise NotFound("Merge-Eintrag nicht gefunden", code="merge_not_found")
        if cand.status != "open":
            raise IntegrityViolation("Merge-Eintrag ist bereits entschieden", code="merge_already_resolved")
        with transaction(self.conn):
            result = self._apply(cand, decision)
            self.audit.record("merge.resolve", "Merge-Entscheidung", entity_type="practice", entity_id=result.practice_id,
                              details={"decision": decision, "provider": cand.provider})
        return result

    def _apply(self, cand, decision: str) -> ResolveResult:
        siblings = [s for s in self.repo.siblings(cand.candidate_key, cand.provider) if s.id != cand.id]
        if decision == "same":
            self.knowledge.attach_to_existing(cand.practice_id, cand.record)
            self.knowledge.repo.record_origin(cand.practice_id, cand.provider, cand.source_ref)
            self.repo.set_status(cand.id, "same")
            for other in siblings:   # ein Kandidat gehört zu genau einer Praxis
                if other.status == "open":
                    self.repo.set_status(other.id, "different")
            return ResolveResult("same", cand.practice_id)
        self.repo.set_status(cand.id, "different")
        others_open = any(s.status == "open" for s in siblings)
        already_same = any(s.status == "same" for s in siblings)
        if others_open or already_same:
            return ResolveResult("different", None)
        result = self.knowledge.upsert_practice(cand.record)   # überall „verschieden“ -> eigene Praxis
        self.knowledge.repo.record_origin(result.practice.id, cand.provider, cand.source_ref)  # type: ignore[arg-type]
        return ResolveResult("different", result.practice.id, created=result.status == "created")
