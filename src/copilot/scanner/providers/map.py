"""MapProvider (VORBEREITET): Karten-/Geodaten für Umkreissuche und exakte Praxiskoordinaten.

Keine Implementierung – bewusst. Vorgesehen sind offene/lizenzierte Geodaten bzw. erlaubte APIs; Scraping von
Google Maps ist ausgeschlossen. Wenn eine Implementierung entsteht, erfüllt sie `SourceProvider` (Praxis-POIs im Gebiet)
und/oder `Geocoder` (Adresse -> exakte Koordinaten; Ergebnis wandert über KnowledgeService.set_exact_location)."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from copilot.config import ProviderConfig
from copilot.domain.geo import GeoPoint
from copilot.scanner.providers.base import Candidate, DiscoveryQuery, ProviderStatus, SourceProvider


class Geocoder(Protocol):
    def geocode(self, street: str | None, plz: str | None, ort: str | None) -> GeoPoint | None:
        """Exakte Koordinaten (uncertainty 0) oder None – niemals eine geratene Position."""


class MapProvider(SourceProvider):
    name = "map"
    description = "Öffentliche Karten-/Standortdaten (vorbereitet, keine Implementierung)"

    def __init__(self, config: ProviderConfig):
        self.config = config

    def status(self) -> tuple[ProviderStatus, str]:
        if not self.config.enabled:
            return ProviderStatus.DISABLED, "providers.map.enabled=false"
        return ProviderStatus.NOT_IMPLEMENTED, "keine Geodatenquelle angebunden (Quelle/Lizenz noch zu entscheiden)"

    def discover(self, query: DiscoveryQuery) -> Iterator[Candidate]:
        self.ensure_ready()
        raise AssertionError("unreachable: ensure_ready() wirft, solange nichts implementiert ist")
