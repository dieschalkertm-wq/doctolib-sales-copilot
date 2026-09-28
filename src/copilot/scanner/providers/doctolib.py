"""DoctolibProvider (VORBEREITET): öffentliche doctolib-Informationen als Datenquelle.

Es gibt kein Architekturverbot. Produktiv wird der Provider erst, wenn ALLES erfüllt ist:
  1. providers.doctolib.enabled = true
  2. vollständige Freigabe-Checkliste (ToS geprüft, robots.txt geprüft, Rate-Limit festgelegt, interne Vorgaben ok,
     freigebende Person) in config/policies.yaml
  3. eine konkrete `DoctolibAccessMethod` ist angebunden (offizielle Schnittstelle, Export oder – wenn erlaubt –
     ein kontrollierter Abruf). Die technische Zugriffsmethode wird SEPARAT entschieden und ist bewusst nicht Teil
     dieser Klasse.
Nicht vorgesehen und nicht zulässig: Umgehung von Schutzmechanismen, Login-Automatisierung, CAPTCHA-Umgehung,
aggressives Massenabrufen. Abrufe laufen über PoliteClient (robots.txt, Rate-Limit, Domain-Freigabe) mit der
FetchPolicy aus `fetch_policy()`, die doctolib.* nur bei vollständiger Freigabe zulässt."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol

from copilot.config import ProviderConfig, ResearchPolicy
from copilot.domain.enums import RobotsStatus, SourceType
from copilot.domain.models import FactDraft
from copilot.knowledge.records import PracticeRecord
from copilot.research.policy import FetchPolicy
from copilot.research.provider import SourceDraft
from copilot.scanner.providers.base import Candidate, DiscoveryQuery, ProviderStatus, SourceProvider


@dataclass(frozen=True)
class DoctolibListing:
    """Ergebnis einer Zugriffsmethode: eine öffentlich sichtbare Praxis samt Profil-URL."""
    record: PracticeRecord
    profile_url: str
    robots_status: RobotsStatus = RobotsStatus.ALLOWED   # NOT_APPLICABLE bei offizieller API/Export


class DoctolibAccessMethod(Protocol):
    def search(self, query: DiscoveryQuery) -> Iterable[DoctolibListing]:
        """Muss Rate-Limits/robots.txt/Nutzungsbedingungen einhalten und höchstens query.max_results liefern."""


class DoctolibProvider(SourceProvider):
    name = "doctolib"
    description = "Öffentliche doctolib-Informationen (vorbereitet: Freigabe + Zugriffsmethode erforderlich)"

    def __init__(self, config: ProviderConfig, access_method: DoctolibAccessMethod | None = None):
        self.config, self.access_method = config, access_method

    def status(self) -> tuple[ProviderStatus, str]:
        if not self.config.enabled:
            return ProviderStatus.DISABLED, "providers.doctolib.enabled=false"
        missing = self.config.clearance.missing()
        if missing:
            return ProviderStatus.NOT_CLEARED, "Freigabe unvollständig: " + ", ".join(missing)
        if self.access_method is None:
            return ProviderStatus.NOT_IMPLEMENTED, "freigegeben, aber keine technische Zugriffsmethode angebunden"
        return ProviderStatus.READY, f"freigegeben durch {self.config.clearance.approved_by}"

    def fetch_policy(self, research: ResearchPolicy) -> FetchPolicy:
        """FetchPolicy für Zugriffsmethoden: erlaubt doctolib.* nur bei vollständiger Freigabe (und weiterhin nur, wenn
        die Domain in research.allowed_domains steht)."""
        if not self.config.enabled or self.config.clearance.missing():
            self.ensure_ready()   # wirft passend (disabled / not_cleared); fehlende Zugriffsmethode ist hier noch ok
        return FetchPolicy(research, allow_doctolib=True)

    def discover(self, query: DiscoveryQuery) -> Iterator[Candidate]:
        self.ensure_ready()
        limit = max(0, min(query.max_results, 200))
        for index, listing in enumerate(self.access_method.search(query)):  # type: ignore[union-attr]
            if index >= limit:
                break
            source = SourceDraft(
                source_type=SourceType.DOCTOLIB_PUBLIC, url=listing.profile_url, publisher="doctolib",
                robots_status=listing.robots_status, reliability=4,
                tos_ref=f"Freigabe: {self.config.clearance.approved_by}")
            fact = FactDraft(key="doctolib_profile_public", value={"url": listing.profile_url}, confidence=0.9,
                             evidence=listing.profile_url)
            yield Candidate(record=listing.record, provider=self.name, source_ref=listing.profile_url,
                            source=source, facts=[fact])
