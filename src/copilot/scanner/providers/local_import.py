"""LocalImportProvider: eigene Listen/Exporte (CSV/TSV). Funktioniert heute und braucht keinen externen Abruf."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from copilot.config import ProviderConfig
from copilot.connectors.imports.csv_practices import CsvPracticeSource
from copilot.scanner.providers.base import Candidate, DiscoveryQuery, ProviderStatus, SourceProvider


class LocalImportProvider(SourceProvider):
    name = "local_import"
    description = "Eigene Listen/Exporte (CSV/TSV) – kein externer Abruf"

    def __init__(self, config: ProviderConfig, path: Path, mapping: dict[str, str] | None = None, *,
                 encoding: str = "auto", delimiter: str = "auto"):
        self.config = config
        self.source = CsvPracticeSource(path, mapping, encoding=encoding, delimiter=delimiter)
        self.rejected: list[tuple[int, list[str]]] = []   # (Zeile, Codes) – nie Inhalte
        self.rows_seen = 0

    def status(self) -> tuple[ProviderStatus, str]:
        if not self.config.enabled:
            return ProviderStatus.DISABLED, "providers.local_import.enabled=false"
        return ProviderStatus.READY, "Datei wird lokal gelesen"

    def discover(self, query: DiscoveryQuery) -> Iterator[Candidate]:
        self.ensure_ready()
        ref = f"file:{self.source.fingerprint()[:16]}"
        for item in self.source.records():
            self.rows_seen += 1
            if item.record is None:
                self.rejected.append((item.row, item.errors))
                continue
            yield Candidate(record=item.record, provider=self.name, source_ref=ref, row=item.row)
