import os
import stat

import pytest

from copilot.config import Policies, ResearchPolicy
from copilot.domain.enums import EntityType, ResearchStatus
from copilot.errors import FetchError, PolicyViolation
from copilot.knowledge.records import PracticeRecord
from copilot.research.client import PoliteClient
from copilot.research.facts import FactService
from copilot.research.policy import FetchPolicy
from copilot.research.practice_website import PracticeWebsiteProvider
from copilot.research.provider import ResearchRequest
from copilot.research.service import ResearchService
from copilot.research.transport import RawResponse

HTML = """<html><head><title>SYNTH Praxis Alpha</title>
<script type="application/ld+json">{"@type": "Physician", "name": "SYNTH Praxis Alpha GbR", "telephone": "+49 681 0000000"}</script>
</head><body>
<a href="tel:+49681000000">Anruf</a> <a href="mailto:info@synth-alpha.invalid?subject=x">Mail</a>
<a href="https://www.doctolib.de/praxis/synth">Termin online</a>
<iframe src="https://www.terminland.de/synth"></iframe>
</body></html>"""


class FakeTransport:
    """Kein Netzwerk in Tests: liefert vorbereitete Antworten und protokolliert Abrufe."""

    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, *, timeout, max_bytes, user_agent):
        self.calls.append(url)
        r = self.routes.get(url)
        if isinstance(r, Exception):
            raise r
        return r or RawResponse(url, 404, {}, b"")


def html(url=None, body=HTML, status=200):
    return RawResponse(url or "", status, {"content-type": "text/html; charset=utf-8"}, body.encode())


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(app, routes, allowed=("synth-alpha.invalid",), **policy):
    research = ResearchPolicy(allowed_domains=list(allowed), booking_signal_domains={"terminland.de": "Terminland"}, **policy)
    policies = Policies(research=research, fact_staleness_days={"default": 180, "doctolib_link_present": 90},
                        expected_fact_keys=[])
    transport, clock = FakeTransport(routes), Clock()
    client = PoliteClient(FetchPolicy(research), transport, "test-agent/1.0", clock=clock.now, sleep=clock.sleep)
    facts = FactService(app.research_repo, policies)
    service = ResearchService(app.conn, app.research_repo, facts, app.knowledge_repo, app.audit, app.settings.raw_cache_dir)
    return PracticeWebsiteProvider(client, policies), service, transport, clock, facts


@pytest.fixture
def practice(app):
    return app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Alpha", plz="66111", ort="Saarbrücken")).practice


def req(practice, url="https://synth-alpha.invalid/"):
    return ResearchRequest(EntityType.PRACTICE, practice.id, url)


def test_success_creates_source_research_and_facts_with_provenance(app, practice):
    provider, service, transport, _, facts = make(app, {"https://synth-alpha.invalid/": html()})
    result = service.run(provider, req(practice))
    keys = {f.key: f for f in result.facts}
    assert set(keys) == {"website_title", "structured_data_name", "public_contact_phone", "public_contact_email",
                         "doctolib_link_present", "online_booking_signal"}
    assert keys["public_contact_email"].value == ["info@synth-alpha.invalid"]
    assert keys["doctolib_link_present"].evidence.startswith("https://www.doctolib.de/")
    assert keys["online_booking_signal"].value == ["Terminland"]
    src = app.research_repo.get_source(result.source.id)
    assert src.url == "https://synth-alpha.invalid/" and src.retrieved_at and len(src.content_hash) == 64
    assert src.robots_status.value == "allowed"
    for f in result.facts:
        assert f.source_id == src.id and f.observed_at == src.retrieved_at and f.stale_after > f.observed_at
        assert facts.view(f).statement().startswith("BELEGT:")
    # doctolib wurde NICHT abgerufen – nur der Link auf der Praxis-Seite wurde erkannt
    assert all("doctolib" not in c for c in transport.calls)
    # Rohinhalt lokal, restriktive Rechte
    raw = app.settings.raw_cache_dir / src.raw_ref
    assert raw.exists() and stat.S_IMODE(os.stat(raw).st_mode) == 0o600
    assert [r["status"] for r in app.research_repo.list_research(EntityType.PRACTICE, practice.id)] == ["succeeded"]


def test_no_negative_or_invented_facts(app, practice):
    provider, service, *_ = make(app, {"https://synth-alpha.invalid/": html(body="<html><head><title>Nur Titel</title></head></html>")})
    result = service.run(provider, req(practice))
    assert [f.key for f in result.facts] == ["website_title"]      # kein "doctolib_link_present=False" o. Ä.


@pytest.mark.parametrize("url,code", [
    ("https://unbekannt.invalid/", "domain_not_allowed"),
    ("https://www.doctolib.de/", "hard_blocked_domain"),
    ("https://www.linkedin.com/in/x", "hard_blocked_domain"),
    ("http://127.0.0.1/", "private_host"),
    ("http://localhost/", "private_host"),
    ("ftp://synth-alpha.invalid/", "scheme_not_allowed"),
])
def test_policy_blocks_before_any_request(app, practice, url, code):
    provider, service, transport, *_ = make(app, {}, allowed=("synth-alpha.invalid", "doctolib.de", "linkedin.com", "127.0.0.1", "localhost"))
    with pytest.raises(PolicyViolation) as exc:
        service.run(provider, req(practice, url))
    assert exc.value.code == code and transport.calls == []
    assert app.research_repo.list_research(EntityType.PRACTICE, practice.id)[0]["status"] == ResearchStatus.BLOCKED.value


def test_empty_allowlist_blocks_everything(app, practice):
    provider, service, transport, *_ = make(app, {}, allowed=())
    with pytest.raises(PolicyViolation) as exc:
        service.run(provider, req(practice))
    assert exc.value.code == "domain_not_allowed" and not transport.calls


def test_robots_disallow_blocks_page_request(app, practice):
    routes = {"https://synth-alpha.invalid/robots.txt": RawResponse("", 200, {}, b"User-agent: *\nDisallow: /"),
              "https://synth-alpha.invalid/": html()}
    provider, service, transport, *_ = make(app, routes)
    with pytest.raises(PolicyViolation) as exc:
        service.run(provider, req(practice))
    assert exc.value.code == "robots_disallowed"
    assert "https://synth-alpha.invalid/" not in transport.calls


def test_robots_only_partial_disallow_allows_other_paths(app, practice):
    routes = {"https://synth-alpha.invalid/robots.txt": RawResponse("", 200, {}, b"User-agent: *\nDisallow: /privat/"),
              "https://synth-alpha.invalid/team": html()}
    provider, service, *_ = make(app, routes)
    assert service.run(provider, req(practice, "https://synth-alpha.invalid/team")).facts


@pytest.mark.parametrize("robots", [RawResponse("", 503, {}, b""), RawResponse("", 403, {}, b""), FetchError("x", code="network_error")])
def test_robots_unreachable_blocks(app, practice, robots):
    provider, service, transport, *_ = make(app, {"https://synth-alpha.invalid/robots.txt": robots})
    with pytest.raises(PolicyViolation) as exc:
        service.run(provider, req(practice))
    assert exc.value.code == "robots_unreachable" and "https://synth-alpha.invalid/" not in transport.calls


def test_missing_robots_txt_allows(app, practice):
    provider, service, *_ = make(app, {"https://synth-alpha.invalid/": html()})   # robots.txt -> 404
    assert service.run(provider, req(practice)).facts


def test_rate_limit_enforced_per_domain(app, practice):
    routes = {"https://synth-alpha.invalid/": html(), "https://synth-alpha.invalid/team": html()}
    provider, service, _, clock, _ = make(app, routes, rate_limit_seconds=2.0)
    service.run(provider, req(practice))
    service.run(provider, req(practice, "https://synth-alpha.invalid/team"))
    assert clock.sleeps and all(s > 0 for s in clock.sleeps)
    # robots.txt (1) + Seite (2) + Seite (3): jeweils >= 2 s Abstand
    assert clock.t >= 4.0


def test_redirect_to_disallowed_domain_is_blocked(app, practice):
    routes = {"https://synth-alpha.invalid/": RawResponse("", 301, {"location": "https://www.doctolib.de/x"}, b"")}
    provider, service, transport, *_ = make(app, routes)
    with pytest.raises(PolicyViolation) as exc:
        service.run(provider, req(practice))
    assert exc.value.code == "hard_blocked_domain" and all("doctolib" not in c for c in transport.calls)


def test_redirect_within_allowed_domain_is_followed_and_source_has_final_url(app, practice):
    routes = {"https://synth-alpha.invalid/": RawResponse("", 302, {"location": "/start"}, b""),
              "https://synth-alpha.invalid/start": html()}
    provider, service, *_ = make(app, routes)
    assert service.run(provider, req(practice)).source.url == "https://synth-alpha.invalid/start"


@pytest.mark.parametrize("response,code", [
    (RawResponse("", 500, {"content-type": "text/html"}, b"x"), "http_status_500"),
    (RawResponse("", 200, {"content-type": "application/pdf"}, b"x"), "unsupported_content_type"),
])
def test_failed_fetch_persists_no_facts(app, practice, response, code):
    provider, service, *_ = make(app, {"https://synth-alpha.invalid/": response})
    with pytest.raises(FetchError) as exc:
        service.run(provider, req(practice))
    assert exc.value.code == code
    assert app.conn.execute("SELECT count(*) FROM r_fact").fetchone()[0] == 0
    assert app.conn.execute("SELECT count(*) FROM r_source").fetchone()[0] == 0
    assert app.research_repo.list_research(EntityType.PRACTICE, practice.id)[0]["status"] == "failed"


def test_rerun_supersedes_previous_facts(app, practice):
    provider, service, *_ , facts = make(app, {"https://synth-alpha.invalid/": html()})
    first = service.run(provider, req(practice))
    second = service.run(provider, req(practice))
    active = app.research_repo.facts_for(EntityType.PRACTICE, practice.id)
    assert {f.id for f in active} == {f.id for f in second.facts}
    assert all(app.research_repo.get_fact(f.id).status.value == "superseded" for f in first.facts)


def test_audit_of_research_has_no_pii(app, practice):
    provider, service, *_ = make(app, {"https://synth-alpha.invalid/": html()})
    service.run(provider, req(practice))
    blob = " ".join(f"{r['summary']} {r['details']}" for r in app.audit.tail())
    assert "synth-alpha" not in blob and "@" not in blob


def test_policy_rejects_fast_rate_limit():
    with pytest.raises(Exception):
        ResearchPolicy(rate_limit_seconds=0.1)
