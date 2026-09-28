"""ResearchEngine: führt Website-Research für Scan-Treffer aus – begrenzt, höflich und nur für freigegebene Domains.

Kein Massenabruf: Obergrenze pro Scan aus config (scanner.research_max_practices), Domain-Freigabe, robots.txt und
Rate-Limit greifen wie beim Einzelabruf (PoliteClient). Nicht freigegebene Domains werden VOR jedem Netzwerkzugriff
übersprungen und erzeugen keine Research-Einträge."""

from __future__ import annotations

from collections.abc import Callable

from copilot.errors import FetchError, PolicyViolation
from copilot.research.policy import FetchPolicy
from copilot.research.provider import ResearchProvider, ResearchRequest
from copilot.research.service import ResearchService
from copilot.domain.enums import EntityType
from copilot.pipeline.worklist import WorklistItem
from copilot.scanner.result import ResearchOutcome

RESEARCHABLE = {"research_website", "refresh_research"}


class ResearchEngine:
    def __init__(self, service: ResearchService, fetch_policy: FetchPolicy, max_practices: int,
                 provider_factory: Callable[[], ResearchProvider]):
        self.service, self.fetch_policy, self.max_practices = service, fetch_policy, max_practices
        self.provider_factory = provider_factory

    def pending(self, items: list[WorklistItem]) -> list[WorklistItem]:
        return [i for i in items if i.next_action in RESEARCHABLE and i.practice.website_url]

    def run(self, items: list[WorklistItem], limit: int) -> list[ResearchOutcome]:
        outcomes: list[ResearchOutcome] = []
        budget = max(0, min(limit, self.max_practices))
        provider: ResearchProvider | None = None
        for item in self.pending(items):
            if budget <= 0:
                break
            url = item.practice.website_url
            pid: int = item.practice.id  # type: ignore[assignment]
            try:
                self.fetch_policy.check_url(url)   # Domain-Freigabe VOR jedem Netzwerkzugriff; kostet kein Budget
            except PolicyViolation as exc:
                outcomes.append(ResearchOutcome(pid, "blocked", exc.code))
                continue
            budget -= 1
            provider = provider or self.provider_factory()
            try:
                result = self.service.run(provider, ResearchRequest(EntityType.PRACTICE, pid, url))
                outcomes.append(ResearchOutcome(pid, "researched", f"{len(result.facts)} Facts", len(result.facts)))
            except PolicyViolation as exc:
                outcomes.append(ResearchOutcome(pid, "blocked", exc.code))
            except FetchError as exc:
                outcomes.append(ResearchOutcome(pid, "failed", exc.code))
        return outcomes
