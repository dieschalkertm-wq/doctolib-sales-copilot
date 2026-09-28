"""Provider für Praxis-Websites bzw. manuell angegebene URLs."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from copilot.config import Policies
from copilot.domain.enums import RobotsStatus, SourceType
from copilot.errors import FetchError, ValidationFailed
from copilot.research.client import PoliteClient
from copilot.research.extract import decode_body, extract_facts
from copilot.research.provider import ProviderOutput, ResearchProvider, ResearchRequest, SourceDraft


class PracticeWebsiteProvider(ResearchProvider):
    name = "practice_website"
    kind = "website_signals"

    def __init__(self, client: PoliteClient, policies: Policies):
        self.client, self.policies = client, policies

    def collect(self, request: ResearchRequest) -> ProviderOutput:
        if not request.url:
            raise ValidationFailed("Für Website-Recherche wird eine URL benötigt", code="url_required")
        result = self.client.fetch(request.url)   # Policy-Gate, robots.txt, Rate-Limit, Redirect-Prüfung
        if not 200 <= result.status < 300:
            raise FetchError(f"HTTP-Status {result.status}", code=f"http_status_{result.status}")
        if "html" not in result.content_type.lower():
            raise FetchError("Kein HTML-Inhalt", code="unsupported_content_type")
        html = decode_body(result.body, result.content_type)
        facts = extract_facts(html, result.final_url, self.policies.research.booking_signal_domains)
        return ProviderOutput(
            source=SourceDraft(
                source_type=SourceType.PRACTICE_WEBSITE, url=result.final_url,
                publisher=urlsplit(result.final_url).hostname, robots_status=RobotsStatus.ALLOWED,
                reliability=4,  # Selbstauskunft der Praxis: gut, aber evtl. veraltet
                tos_ref="robots.txt geprüft; Nutzungsbedingungen der Site nicht maschinell geprüft",
                content_hash=hashlib.sha256(result.body).hexdigest(), raw_content=result.body),
            facts=facts)
