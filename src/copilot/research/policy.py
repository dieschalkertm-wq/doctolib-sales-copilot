"""Policy-Gate für Web-Abrufe (ARCHITECTURE §7). Unbekannte Domains sind gesperrt, bis sie freigegeben sind."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from copilot.config import ResearchPolicy
from copilot.errors import PolicyViolation

# In Phase 1 hart gesperrt (unabhängig von der Konfiguration): kein doctolib-Scraping, kein LinkedIn-Abruf.
HARD_BLOCKED_LABELS = frozenset({"doctolib"})
HARD_BLOCKED_DOMAINS = ("linkedin.com", "licdn.com")


def host_matches(host: str, domain: str) -> bool:
    domain = domain.lower().strip(".")
    return host == domain or host.endswith("." + domain)


def is_hard_blocked(host: str) -> bool:
    return bool(HARD_BLOCKED_LABELS & set(host.split("."))) or any(host_matches(host, d) for d in HARD_BLOCKED_DOMAINS)


class FetchPolicy:
    def __init__(self, research: ResearchPolicy):
        self.research = research

    def check_url(self, url: str) -> str:
        """Gibt den Host zurück oder wirft PolicyViolation (mit maschinenlesbarem Code)."""
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            raise PolicyViolation("Nur http(s) erlaubt", code="scheme_not_allowed")
        host = (parts.hostname or "").lower().strip(".")
        if not host or parts.username or parts.password:
            raise PolicyViolation("Ungültiger Host", code="invalid_host")
        try:
            ipaddress.ip_address(host)
            raise PolicyViolation("IP-Adressen und interne Hosts sind gesperrt", code="private_host")
        except ValueError:
            pass
        if host == "localhost" or host.endswith((".local", ".localhost", ".internal", ".lan")):
            raise PolicyViolation("Interne Hosts sind gesperrt", code="private_host")
        if is_hard_blocked(host):
            raise PolicyViolation("Domain ist in dieser Phase hart gesperrt", code="hard_blocked_domain")
        if not any(host_matches(host, d) for d in self.research.allowed_domains):
            raise PolicyViolation(
                f"Domain '{host}' ist nicht freigegeben (config/policies.yaml: research.allowed_domains)",
                code="domain_not_allowed")
        return host
