"""Composition Root: baut Verbindung, Konfiguration, Repositories und Services zusammen."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from copilot.knowledge.merge import MergeService
from copilot.llm.context import ContextBuilder
from copilot.llm.gateway import LLMGateway
from copilot.research.client import PoliteClient
from copilot.research.policy import FetchPolicy
from copilot.research.practice_website import PracticeWebsiteProvider
from copilot.research.provider import ResearchProvider
from copilot.research.service import ResearchService
from copilot.research.transport import UrllibTransport
from copilot.scanner.area import LocationResolver
from copilot.scanner.builder import ProspectListBuilder
from copilot.scanner.ingest import CandidateIngestor
from copilot.scanner.matcher import ExistingDataMatcher
from copilot.scanner.network import NetworkAnalyzer
from copilot.scanner.research import ResearchEngine
from copilot.scanner.scanner import TerritoryScanner
from copilot.storage.merge import MergeRepository

from copilot.config import Policies, Settings, load_policies
from copilot.domain.territory import Territory
from copilot.knowledge.network import NetworkService, ReferralRules
from copilot.knowledge.service import KnowledgeService
from copilot.knowledge.specialties import SpecialtyCatalog
from copilot.pipeline.scoring import ScoringConfig
from copilot.pipeline.service import PipelineService
from copilot.pipeline.worklist import WorklistService
from copilot.research.facts import FactService
from copilot.storage.audit import AuditLog
from copilot.storage.db import connect, migrate
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.network import NetworkRepository
from copilot.storage.pipeline import PipelineRepository
from copilot.storage.research import ResearchRepository


@dataclass
class App:
    settings: Settings
    conn: sqlite3.Connection
    policies: Policies
    territory: Territory
    catalog: SpecialtyCatalog
    audit: AuditLog
    knowledge_repo: KnowledgeRepository
    research_repo: ResearchRepository
    network_repo: NetworkRepository
    pipeline_repo: PipelineRepository
    knowledge: KnowledgeService
    network: NetworkService
    pipeline: PipelineService
    facts: FactService
    worklist: WorklistService
    merge_repo: MergeRepository
    merge: MergeService
    research_service: ResearchService
    scanner: TerritoryScanner
    llm_context: ContextBuilder
    llm: LLMGateway

    def research_provider(self) -> ResearchProvider:
        """Website-Provider mit echtem Transport (Policy-Gate, robots.txt, Rate-Limit)."""
        client = PoliteClient(FetchPolicy(self.policies.research), UrllibTransport(), self.settings.user_agent)
        return PracticeWebsiteProvider(client, self.policies)

    @classmethod
    def open(cls, settings: Settings) -> "App":
        conn = connect(settings.db_path)
        migrate(conn)
        policies = load_policies(settings.config_dir)
        territory = Territory.load(settings.config_dir)
        catalog = SpecialtyCatalog.load(settings.config_dir)
        knowledge_repo, research_repo = KnowledgeRepository(conn), ResearchRepository(conn)
        network_repo, pipeline_repo = NetworkRepository(conn), PipelineRepository(conn)
        catalog.seed(knowledge_repo)
        facts = FactService(research_repo, policies)
        merge_repo = MergeRepository(conn)
        audit = AuditLog(conn, settings.actor)
        rules = ReferralRules.load(settings.config_dir)
        knowledge = KnowledgeService(knowledge_repo, territory, catalog)
        network = NetworkService(network_repo, knowledge_repo, research_repo, rules, territory)
        worklist = WorklistService(knowledge_repo, pipeline_repo, network_repo, facts,
                                   ScoringConfig.load(settings.config_dir), territory)
        research_service = ResearchService(conn, research_repo, facts, knowledge_repo, audit, settings.raw_cache_dir)
        app = cls(
            settings=settings, conn=conn, policies=policies, territory=territory, catalog=catalog, audit=audit,
            knowledge_repo=knowledge_repo, research_repo=research_repo,
            network_repo=network_repo, pipeline_repo=pipeline_repo,
            knowledge=knowledge, network=network, pipeline=PipelineService(pipeline_repo, knowledge_repo),
            facts=facts, worklist=worklist, merge_repo=merge_repo,
            merge=MergeService(merge_repo, knowledge, audit, conn), research_service=research_service,
            scanner=None,  # type: ignore[arg-type]
            llm_context=ContextBuilder(knowledge_repo, facts, policies.llm),
            llm=LLMGateway(policies.llm, None, audit),   # kein Anbieter angebunden
        )
        matcher = ExistingDataMatcher(knowledge_repo, merge_repo)
        app.scanner = TerritoryScanner(
            conn=conn, territory=territory, catalog=catalog, policies=policies, knowledge=knowledge_repo,
            merge=merge_repo,
            resolver=LocationResolver(territory, knowledge_repo, pipeline_repo, rules, policies.scanner),
            matcher=matcher,
            ingestor=CandidateIngestor(knowledge, matcher, merge_repo, research_service, territory, catalog),
            worklist=worklist,
            builder=ProspectListBuilder(knowledge_repo, research_repo, network_repo, pipeline_repo, facts, network),
            network=NetworkAnalyzer(network, pipeline_repo),
            research=ResearchEngine(research_service, FetchPolicy(policies.research),
                                    policies.scanner.research_max_practices, app.research_provider),
            audit=audit)
        return app

    def close(self) -> None:
        self.conn.close()
