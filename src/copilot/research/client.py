"""Höflicher Abruf-Client: Policy-Gate -> robots.txt -> Rate-Limit -> Abruf, pro Redirect-Hop."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

from copilot.errors import FetchError, PolicyViolation
from copilot.research.policy import FetchPolicy
from copilot.research.transport import RawResponse, Transport


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


class PoliteClient:
    def __init__(self, policy: FetchPolicy, transport: Transport, user_agent: str, *,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep):
        self.policy, self.transport, self.user_agent = policy, transport, user_agent
        self.clock, self.sleep = clock, sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotFileParser | str] = {}   # origin -> Parser | "allow_all" | Fehlercode

    # -- Rate-Limit: max. 1 Request/Domäne/rate_limit_seconds (robots.txt zählt mit)
    def _get(self, url: str, host: str) -> RawResponse:
        r = self.policy.research
        last = self._last_request.get(host)
        if last is not None:
            wait = last + r.rate_limit_seconds - self.clock()
            if wait > 0:
                self.sleep(wait)
        try:
            return self.transport.get(url, timeout=r.timeout_seconds, max_bytes=r.max_bytes, user_agent=self.user_agent)
        finally:
            self._last_request[host] = self.clock()

    def _load_robots(self, origin: str) -> RobotFileParser | str:
        url = origin + "/robots.txt"
        for _ in range(self.policy.research.max_redirects + 1):
            host = self.policy.check_url(url)  # Domain-Gate auch für robots.txt-Redirects
            try:
                resp = self._get(url, host)
            except FetchError:
                return "robots_unreachable"      # Netzwerkfehler: konservativ sperren
            if 300 <= resp.status < 400 and resp.headers.get("location"):
                url = urljoin(url, resp.headers["location"])
                continue
            if resp.status in (401, 403) or resp.status >= 500:
                return "robots_unreachable"      # nicht lesbar/Serverfehler: konservativ sperren
            if resp.status >= 400:
                return "allow_all"               # 404 etc.: keine robots.txt vorhanden
            parser = RobotFileParser()
            parser.parse(resp.body.decode("utf-8", errors="replace").splitlines())
            return parser
        return "robots_unreachable"

    def _check_robots(self, url: str) -> None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            self._robots[origin] = self._load_robots(origin)
        entry = self._robots[origin]
        if entry == "robots_unreachable":
            raise PolicyViolation("robots.txt nicht abrufbar – vorsichtshalber kein Abruf", code="robots_unreachable")
        if isinstance(entry, RobotFileParser) and not entry.can_fetch(self.user_agent, url):
            raise PolicyViolation("robots.txt verbietet den Abruf", code="robots_disallowed")

    def fetch(self, url: str) -> FetchResult:
        current = url
        for _ in range(self.policy.research.max_redirects + 1):
            host = self.policy.check_url(current)
            self._check_robots(current)
            resp = self._get(current, host)
            if 300 <= resp.status < 400 and resp.headers.get("location"):
                current = urljoin(current, resp.headers["location"])
                continue
            return FetchResult(url, current, resp.status, resp.headers.get("content-type", ""), resp.body)
        raise FetchError("Zu viele Weiterleitungen", code="too_many_redirects")
