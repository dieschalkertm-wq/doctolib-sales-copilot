"""Pipeline-Service: Kunden- und Prospect-Status (Vertriebsdaten, getrennt von Knowledge/Research)."""

from __future__ import annotations

from copilot.domain.enums import ProspectStage
from copilot.domain.models import Customer, Prospect
from copilot.errors import NotFound
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.pipeline import PipelineRepository


class PipelineService:
    def __init__(self, repo: PipelineRepository, knowledge: KnowledgeRepository):
        self.repo, self.knowledge = repo, knowledge

    def _require_practice(self, practice_id: int) -> None:
        if self.knowledge.get_practice(practice_id) is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")

    def mark_customer(self, practice_id: int) -> tuple[Customer, bool]:
        self._require_practice(practice_id)
        existing = self.repo.get_customer(practice_id)
        if existing:
            return existing, False
        customer = self.repo.insert_customer(Customer(practice_id=practice_id))
        prospect = self.repo.get_prospect(practice_id)
        if prospect and prospect.stage is not ProspectStage.WON:
            self.repo.conn.execute("UPDATE p_prospect SET stage='won' WHERE practice_id=?", (practice_id,))
        return customer, True

    def ensure_prospect(self, practice_id: int) -> tuple[Prospect | None, bool]:
        """Kundenpraxen werden nicht (neu) zum Prospect -> (None, False)."""
        self._require_practice(practice_id)
        if self.repo.get_customer(practice_id):
            return None, False
        existing = self.repo.get_prospect(practice_id)
        if existing:
            return existing, False
        return self.repo.insert_prospect(practice_id), True
