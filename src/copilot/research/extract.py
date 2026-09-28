"""Deterministische Extraktion aus HTML (stdlib). Es entstehen nur POSITIVE, belegte Signale:
Das Fehlen eines Hinweises ist kein Fact (→ bleibt 'unbekannt')."""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from copilot.domain.models import FactDraft
from copilot.research.policy import host_matches, is_doctolib_host

_MEDICAL_TYPES = {"Physician", "MedicalClinic", "MedicalBusiness", "Dentist", "MedicalOrganization", "Hospital"}
_LINK_ATTRS = {"a": "href", "iframe": "src", "script": "src", "form": "action", "link": "href"}


class _Collector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.links: list[str] = []
        self.jsonld: list[str] = []
        self._in_title = False
        self._in_jsonld = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        attrs_d = {k: v for k, v in attrs if v is not None}
        if tag == "title":
            self._in_title = True
        elif tag == "script" and attrs_d.get("type", "").lower() == "application/ld+json":
            self._in_jsonld, self._buf = True, []
        if tag in _LINK_ATTRS and (value := attrs_d.get(_LINK_ATTRS[tag])):
            self.links.append(value.strip())

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_jsonld:
            self.jsonld.append("".join(self._buf))
            self._in_jsonld = False

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._in_jsonld:
            self._buf.append(data)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def _uniq(items: list[str], limit: int) -> list[str]:
    seen: dict[str, None] = {}
    for item in items:
        seen.setdefault(item, None)
    return list(seen)[:limit]


def decode_body(body: bytes, content_type: str) -> str:
    header = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    meta = re.search(rb"charset=[\"']?([\w-]+)", body[:2048], re.I)
    charset = header.group(1) if header else (meta.group(1).decode("ascii") if meta else "utf-8")
    try:
        return body.decode(charset, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")


def extract_facts(html: str, base_url: str, booking_domains: dict[str, str]) -> list[FactDraft]:
    collector = _Collector()
    collector.feed(html)
    facts: list[FactDraft] = []

    title = re.sub(r"\s+", " ", "".join(collector.title_parts)).strip()
    if title:
        facts.append(FactDraft(key="website_title", value=title[:200], confidence=0.95, evidence="<title>"))

    names, phones = [], []
    for block in collector.jsonld:
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for node in _walk(data):
            types = node.get("@type")
            types = [types] if isinstance(types, str) else (types or [])
            if _MEDICAL_TYPES & set(map(str, types)):
                if isinstance(node.get("name"), str) and node["name"].strip():
                    names.append(node["name"].strip()[:200])
                if isinstance(node.get("telephone"), str) and node["telephone"].strip():
                    phones.append(node["telephone"].strip())
    if names:
        facts.append(FactDraft(key="structured_data_name", value=names[0], confidence=0.9,
                               evidence="JSON-LD (schema.org) name"))

    emails: list[str] = []
    resolved: list[str] = []
    for link in collector.links:
        lower = link.lower()
        if lower.startswith("tel:"):
            phones.append(link[4:].strip())
        elif lower.startswith("mailto:"):
            emails.append(link[7:].split("?")[0].strip())
        elif not lower.startswith(("javascript:", "#", "data:")):
            resolved.append(urljoin(base_url, link))
    if phones := _uniq([p for p in phones if p], 3):
        facts.append(FactDraft(key="public_contact_phone", value=phones, confidence=0.8, evidence="tel:-Link / JSON-LD"))
    if emails := _uniq([e for e in emails if "@" in e], 3):
        facts.append(FactDraft(key="public_contact_email", value=emails, confidence=0.8, evidence="mailto:-Link"))

    doctolib_urls, booking_names, booking_evidence = [], [], None
    for url in resolved:
        host = (urlsplit(url).hostname or "").lower()
        if is_doctolib_host(host):
            doctolib_urls.append(url[:300])
            continue
        for domain, provider in booking_domains.items():
            if host_matches(host, domain):
                booking_names.append(provider)
                booking_evidence = booking_evidence or url[:300]
    if doctolib_urls:  # Erkennung nur über Verweise auf der Praxis-Website – doctolib selbst wird nie abgerufen
        urls = _uniq(doctolib_urls, 5)
        facts.append(FactDraft(key="doctolib_link_present", value=urls, confidence=0.9, evidence=urls[0]))
    if booking_names:
        facts.append(FactDraft(key="online_booking_signal", value=sorted(set(booking_names)), confidence=0.8,
                               evidence=booking_evidence))
    return facts
