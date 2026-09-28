"""Composition Root: baut Verbindung, Konfiguration, Repositories und Services zusammen."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

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
        return cls(
            settings=settings, conn=conn, policies=policies, territory=territory, catalog=catalog,
            audit=AuditLog(conn, settings.actor),
            knowledge_repo=knowledge_repo, research_repo=research_repo,
            network_repo=network_repo, pipeline_repo=pipeline_repo,
            knowledge=KnowledgeService(knowledge_repo, territory, catalog),
            network=NetworkService(network_repo, knowledge_repo, research_repo, ReferralRules.load(settings.config_dir)),
            pipeline=PipelineService(pipeline_repo, knowledge_repo),
            facts=facts,
            worklist=WorklistService(knowledge_repo, pipeline_repo, network_repo, facts,
                                     ScoringConfig.load(settings.config_dir), territory),
        )

    def close(self) -> None:
        self.conn.close()
