"""HTTP-Transport (stdlib). Folgt bewusst KEINEN Redirects – jeder Hop läuft durch das Policy-Gate."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Protocol

from copilot.errors import FetchError


@dataclass
class RawResponse:
    url: str
    status: int
    headers: dict[str, str] = field(default_factory=dict)  # Schlüssel kleingeschrieben
    body: bytes = b""


class Transport(Protocol):
    def get(self, url: str, *, timeout: float, max_bytes: int, user_agent: str) -> RawResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401
        return None


class UrllibTransport:
    def get(self, url: str, *, timeout: float, max_bytes: int, user_agent: str) -> RawResponse:
        request = urllib.request.Request(
            url, headers={"User-Agent": user_agent, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.1"})
        opener = urllib.request.build_opener(_NoRedirect)
        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as err:
            response = err
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise FetchError("Netzwerkfehler beim Abruf", code="network_error") from exc
        with response:
            body = response.read(max_bytes + 1)
            status = response.getcode()
            headers = {k.lower(): v for k, v in response.headers.items()}
        if len(body) > max_bytes:
            raise FetchError("Antwort zu groß", code="response_too_large")
        return RawResponse(url=url, status=int(status), headers=headers, body=body)
