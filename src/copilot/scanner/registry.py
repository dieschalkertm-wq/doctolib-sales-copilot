"""Übersicht aller Provider mit ehrlichem Status: was funktioniert heute, was ist nur vorbereitet."""

from __future__ import annotations

from dataclasses import dataclass

from copilot.config import Policies
from copilot.scanner.providers.base import ProviderStatus
from copilot.scanner.providers.doctolib import DoctolibProvider
from copilot.scanner.providers.map import MapProvider


@dataclass(frozen=True)
class ProviderInfo:
    role: str      # source | research | llm
    name: str
    status: str
    detail: str


def describe_providers(policies: Policies) -> list[ProviderInfo]:
    cfg = policies.providers
    infos = [
        ProviderInfo("source", "local_import",
                     ProviderStatus.READY.value if cfg.local_import.enabled else ProviderStatus.DISABLED.value,
                     "eigene Listen/Exporte (--from-file), kein externer Abruf"),
    ]
    domains = policies.research.allowed_domains
    if not cfg.practice_website.enabled:
        infos.append(ProviderInfo("research", "practice_website", ProviderStatus.DISABLED.value,
                                  "providers.practice_website.enabled=false"))
    else:
        infos.append(ProviderInfo("research", "practice_website", ProviderStatus.READY.value,
                                  f"{len(domains)} Domains freigegeben" if domains else
                                  "läuft, aber KEINE Domain freigegeben – alle Abrufe werden blockiert"))
    for provider in (MapProvider(cfg.map), DoctolibProvider(cfg.doctolib, None)):
        status, detail = provider.status()
        infos.append(ProviderInfo("source", provider.name, status.value, f"{provider.description}; {detail}"))
    llm = policies.llm
    infos.append(ProviderInfo(
        "llm", "llm_gateway", "disabled" if not llm.enabled else "ready",
        "Gateway vorbereitet, kein Anbieter angebunden; externe Anbieter " + ("erlaubt" if llm.allow_external else "nicht erlaubt")))
    return infos
