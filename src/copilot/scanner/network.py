"""NetworkAnalyzer: leitet für Scan-Treffer mögliche Überweiserbezüge zu Kundenpraxen ab.

Ergebnis ist ausschließlich origin=derived (Regel, nicht belegt). Eine belegte Beziehung (observed) entsteht nur über
einen Fact (NetworkService.record_observed); die Datenbankregeln werden hier nicht umgangen."""

from __future__ import annotations

from copilot.knowledge.network import NetworkService
from copilot.scanner.result import NetworkSummary
from copilot.storage.pipeline import PipelineRepository


class NetworkAnalyzer:
    def __init__(self, network: NetworkService, pipeline: PipelineRepository):
        self.network, self.pipeline = network, pipeline

    def analyze(self, practice_ids: set[int], radius_km: float) -> NetworkSummary:
        summary = NetworkSummary()
        if not practice_ids:
            return summary
        for customer_id in sorted(self.pipeline.customer_practice_ids()):
            result = self.network.derive_for_practice(customer_id, radius_km, candidate_ids=practice_ids)
            summary.created += result.created
            summary.existing += result.existing
            summary.skipped_no_geo += result.skipped_no_geo
        return summary
