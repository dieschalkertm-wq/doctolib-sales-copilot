import json

import pytest

from copilot.config import Clearance, ProviderConfig, ResearchPolicy
from copilot.connectors.imports.csv_practices import CsvPracticeSource
from copilot.connectors.imports.service import PracticeImporter
from copilot.domain.enums import EntityType, ProspectStage, RelationOrigin
from copilot.errors import (FetchError, PolicyViolation, ProviderNotAvailable, ProviderNotCleared,
                            ValidationFailed)
from copilot.research.client import PoliteClient
from copilot.research.policy import FetchPolicy
from copilot.research.practice_website import PracticeWebsiteProvider
from copilot.scanner.research import ResearchEngine
from copilot.scanner.scanner import ScanRequest
from tests.test_research import Clock, FakeTransport, html


def by_name(result):
    return {i.practice.name: i for i in result.items}


def n(app, table):
    return app.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


@pytest.fixture
def loaded(app, synthetic_file):
    PracticeImporter(app.knowledge, app.pipeline, app.audit, app.conn).run(CsvPracticeSource(synthetic_file))
    return {p.name: p for p in app.knowledge_repo.list_practices()}


def scan(app, **kw):
    return app.scanner.scan(ScanRequest(**kw))


# ---------------------------------------------------------------- Matching statt Duplizieren
def test_scan_matches_existing_data_instead_of_creating_duplicates(app, loaded, scan_source):
    before = n(app, "k_practice")
    result = scan(app, scope="Saarbrücken", radius_km=10, from_files=[scan_source])
    (name, rep, rejected), = result.ingest
    assert name == "local_import" and rep.seen == 10
    assert (rep.created, rep.attached, rep.queued, rep.skipped_outside) == (4, 3, 2, 1)
    assert [r[0] for r in rejected] == [11, 12] and [r[1] for r in rejected] == [["missing_name"], ["invalid_geo"]]
    assert n(app, "k_practice") == before + 4          # Sigma, Omega, Tau, Rho – nicht 10
    # Beta wurde nicht dupliziert, sondern bekommt eine zweite Herkunft
    beta = loaded["SYNTH Kardiologie Beta"]
    assert len(app.knowledge_repo.origins_of(beta.id)) == 2
    # mögliche Dubletten: nichts zusammengeführt, aber in der Queue
    queue = app.merge_repo.list("open")
    assert {(m.record.name, m.practice_id) for m in queue} == {
        ("SYNTH MVZ Nachfolge", loaded["SYNTH Orthopädie Gamma"].id),
        ("SYNTH Orthopädie Gamma", loaded["SYNTH Orthopädie Gamma"].id)}
    assert all(0 < m.confidence < 1 and m.reasons for m in queue)
    assert "SYNTH MVZ Nachfolge" not in {p.name for p in app.knowledge_repo.list_practices()}


def test_scan_is_idempotent(app, loaded, scan_source):
    scan(app, scope="Saarbrücken", from_files=[scan_source])
    count, queue = n(app, "k_practice"), n(app, "k_merge_candidate")
    again = scan(app, scope="Saarbrücken", from_files=[scan_source])
    rep = again.ingest[0][1]
    assert rep.created == 0 and rep.queued == 0 and rep.already_queued == 2
    assert n(app, "k_practice") == count and n(app, "k_merge_candidate") == queue


def test_exact_coordinates_from_source_upgrade_precision(app, loaded, tmp_path):
    f = tmp_path / "geo.txt"
    f.write_text("Praxisname;Straße;PLZ;Ort;Breitengrad;Längengrad\nSYNTH Kardiologie Beta;Musterweg 2;66113;Saarbrücken;49,2300;7,0100\n",
                 encoding="utf-8")
    scan(app, scope="Saarbrücken", from_files=[f])
    beta = app.knowledge_repo.get_practice(loaded["SYNTH Kardiologie Beta"].id)
    assert beta.geo_precision.value == "exact" and (beta.lat, beta.lon) == (49.23, 7.01)


def test_dry_run_previews_without_any_write(app, loaded, scan_source):
    tables = ["k_practice", "k_practice_origin", "k_merge_candidate", "k_network_relationship", "a_audit_event", "r_research"]
    before = {t: n(app, t) for t in tables}
    result = scan(app, scope="Saarbrücken", radius_km=10, from_files=[scan_source], dry_run=True, research=True)
    assert {t: n(app, t) for t in tables} == before
    assert result.dry_run and any(i.is_new for i in result.items)
    assert result.research == []                       # im Dry-Run kein einziger Abruf


def test_scan_audit_has_no_pii(app, loaded, scan_source):
    scan(app, scope="Saarbrücken", radius_km=10, from_files=[scan_source])
    event = app.audit.tail(1)[0]
    assert event["event_type"] == "territory.scan"
    assert "SYNTH" not in event["details"] and "Saarbr" not in event["details"]


# ---------------------------------------------------------------- Gebiet / Genauigkeit
def test_place_vs_radius_and_uncertainty(app, loaded):
    place = scan(app, scope="Saarbrücken")
    assert {i.practice.ort_key for i in place.items} == {"saarbruecken"}
    assert "Ortsangabe" in place.area_description

    r10 = scan(app, scope="Saarbrücken", radius_km=10)
    voelk = by_name(r10)["SYNTH Hautarzt Delta"]
    assert voelk.match.certainty.value == "possible" and "möglicherweise" in voelk.distance and "±5" in voelk.distance
    assert by_name(r10)["SYNTH Kardiologie Beta"].match.certainty.value == "inside"
    assert any("Ortsmittelpunkt" in note for note in r10.accuracy_notes)

    strict = scan(app, scope="Saarbrücken", radius_km=10, strict_radius=True)
    assert "SYNTH Hautarzt Delta" not in by_name(strict) and strict.dropped_uncertain == 1
    assert "SYNTH Hautarzt Delta" in by_name(scan(app, scope="Saarbrücken", radius_km=25))
    assert "SYNTH Hautarzt Delta" not in by_name(scan(app, scope="Saarbrücken", radius_km=6))
    assert "SYNTH Hausarztpraxis Epsilon" not in by_name(r10)                    # Trier, ~60 km

    exact = by_name(scan(app, scope="Saarbrücken", radius_km=10, from_files=[]))  # keine falsche Präzision ohne Koordinaten
    assert all(("≈" in i.distance or "Ortsmittelpunkt" in i.distance) for i in exact.values()
               if i.practice.geo_precision.value == "place" and i.match.distance_km is not None)


def test_exact_practice_shows_precise_distance(app, loaded, scan_source):
    result = scan(app, scope="Saarbrücken", radius_km=10, from_files=[scan_source])
    omega = by_name(result)["SYNTH HNO Omega"]
    assert omega.practice.geo_precision.value == "exact" and "≈" not in omega.distance and omega.is_new


def test_practices_without_geo_are_reported_not_guessed(app, loaded):
    app.knowledge.upsert_practice(__import__("copilot.knowledge.records", fromlist=["PracticeRecord"]).PracticeRecord(
        name="SYNTH Ort unbekannt", plz="66999", ort="Unbekanntdorf"))
    result = scan(app, scope="Saarbrücken", radius_km=10)
    assert result.no_geo == 1 and "SYNTH Ort unbekannt" not in by_name(result)


def test_around_practice(app, loaded):
    beta = loaded["SYNTH Kardiologie Beta"]
    result = scan(app, around_practice=beta.id, radius_km=5)
    assert "SYNTH Kardiologie Beta" not in by_name(result)
    assert result.area_label == f"5 km um Praxis #{beta.id}"


# ---------------------------------------------------------------- Fachrichtungen
def test_specialty_filters_use_catalog_aliases(app, loaded, scan_source):
    r = scan(app, scope="Saarbrücken", specialties=["Orthopädie"], from_files=[scan_source])
    assert {i.practice.name for i in r.items} == {"SYNTH Orthopädie Gamma"}
    assert r.ingest[0][1].skipped_specialty > 0
    multi = scan(app, scope="Saarbrücken", specialties=["hno", "Hautarzt", "kardiologie"])
    assert {i.specialties[0] for i in multi.items} <= {"Hals-Nasen-Ohren-Heilkunde", "Dermatologie", "Kardiologie"}
    with pytest.raises(ValidationFailed) as exc:
        scan(app, scope="Saarbrücken", specialties=["Zauberheilkunde"])
    assert exc.value.code == "unknown_specialty"


# ---------------------------------------------------------------- vorhandene Daten
def test_existing_status_is_respected(app, loaded):
    a, b, c, d = (loaded[f"SYNTH {x}"] for x in ("Hausarztpraxis Alpha", "Kardiologie Beta", "Orthopädie Gamma", "Neurologie Zeta"))
    app.pipeline.mark_customer(a.id)                                         # A = Kunde
    app.pipeline.ensure_prospect(b.id)                                       # B = Prospect
    app.pipeline.ensure_prospect(c.id)
    app.conn.execute("UPDATE p_prospect SET stage = ? WHERE practice_id = ?", (ProspectStage.CONTACTED.value, c.id))  # C = kontaktiert
    result = scan(app, scope="Saarbrücken")                                  # D = unbekannt
    reasons = {p.name: r for p, r in result.excluded}
    assert reasons == {a.name: "customer"}
    items = by_name(result)
    assert items[b.name].status == "prospect" and items[b.name].stage == "identified"
    assert items[c.name].stage == "contacted" and items[d.name].status == "unassigned"
    unworked = scan(app, scope="Saarbrücken", unworked=True)
    assert c.name not in by_name(unworked) and dict((p.name, r) for p, r in unworked.excluded)[c.name] == "already_worked"
    assert n(app, "k_practice") == 7                                          # der Scan hat keine Datensätze vermehrt


# ---------------------------------------------------------------- Netzwerk
def test_around_customers_finds_relevant_specialists_and_derives_only(app, loaded, scan_source):
    gp = loaded["SYNTH Hausarztpraxis Alpha"]
    app.pipeline.mark_customer(gp.id)
    result = scan(app, scope="Saarbrücken", around_customers=True, radius_km=10, from_files=[scan_source])
    names = set(by_name(result))
    assert {"SYNTH Kardiologie Beta", "SYNTH Orthopädie Gamma", "SYNTH HNO Omega", "SYNTH Dermatologie Sigma"} <= names
    assert gp.name not in names and "SYNTH Neurologie Zeta" not in names      # Zeta: Fachrichtung unbekannt
    beta = by_name(result)["SYNTH Kardiologie Beta"]
    assert beta.match.anchor_practice_id == gp.id
    assert any("ABGELEITET" in line and "nicht belegt" in line and f"Kundenpraxis #{gp.id}" in line for line in beta.network)
    rels = app.network_repo.for_entity(EntityType.PRACTICE, gp.id, direction="out")
    assert rels and {r.origin for r in rels} == {RelationOrigin.DERIVED}      # nie 'observed' aus einem Scan
    assert all(r.rule_id and r.fact_id is None and r.distance_uncertainty_km is not None for r in rels)
    assert "BEOBACHTET" not in " ".join(line for i in result.items for line in i.network)
    assert any(r.criterion == "referral_proximity" and "nicht belegt" in r.explanation for r in beta.worklist.reasons)


def test_observed_relationship_still_requires_fact(app, loaded):
    a, b = loaded["SYNTH Hausarztpraxis Alpha"], loaded["SYNTH Kardiologie Beta"]
    with pytest.raises(Exception):
        app.conn.execute("INSERT INTO k_network_relationship (from_type, from_id, to_type, to_id, rel_type, origin, created_at)"
                         " VALUES ('practice', ?, 'practice', ?, 'refers_to', 'observed', 'x')", (a.id, b.id))


# ---------------------------------------------------------------- Research-Engine
def engine(app, routes, allowed, max_practices=25):
    research = ResearchPolicy(allowed_domains=allowed, booking_signal_domains={"terminland.de": "Terminland"})
    transport, clock = FakeTransport(routes), Clock()
    client = PoliteClient(FetchPolicy(research), transport, "test/1.0", clock=clock.now, sleep=clock.sleep)
    provider = PracticeWebsiteProvider(client, app.policies)
    return ResearchEngine(app.research_service, FetchPolicy(research), max_practices, lambda: provider), transport


def test_scan_research_runs_only_for_allowed_domains_and_feeds_back(app, loaded):
    app.scanner.research, transport = engine(app, {"https://synth-alpha.invalid": html()}, ["synth-alpha.invalid"])
    result = scan(app, scope="Saarbrücken", research=True)
    outcomes = {o.practice_id: o for o in result.research}
    alpha, beta = loaded["SYNTH Hausarztpraxis Alpha"], loaded["SYNTH Kardiologie Beta"]
    assert outcomes[alpha.id].status == "researched" and outcomes[alpha.id].fact_count > 0
    assert outcomes[beta.id].status == "blocked" and outcomes[beta.id].detail == "domain_not_allowed"
    assert all("synth-beta" not in c for c in transport.calls)               # nicht freigegeben -> kein einziger Abruf
    assert n(app, "r_research") == 1                                          # blockierte werden nicht als Läufe protokolliert
    # die neue Recherche fließt zurück: Alpha hat einen doctolib-Link (belegt) -> ausgeschlossen
    assert alpha.name not in by_name(result)
    assert dict((p.name, r) for p, r in result.excluded)[alpha.name] == "already_doctolib_recognised"


def test_research_is_capped_per_scan(app, loaded):
    routes = {"https://synth-alpha.invalid": html(body="<title>A</title>"), "https://synth-beta.invalid": html(body="<title>B</title>"),
              "https://synth-delta.invalid": html(body="<title>D</title>")}
    app.scanner.research, transport = engine(app, routes, ["synth-alpha.invalid", "synth-beta.invalid", "synth-delta.invalid"])
    result = scan(app, scope="Saarland", research=True, research_limit=2)
    assert len([o for o in result.research if o.status == "researched"]) == 2
    app.scanner.research, _ = engine(app, routes, ["synth-alpha.invalid", "synth-beta.invalid", "synth-delta.invalid"], max_practices=1)
    assert len(scan(app, scope="Saarland", research=True, research_limit=50).research) <= 3   # Konfig-Obergrenze gewinnt


def test_scan_without_research_flag_only_reports_pending(app, loaded):
    result = scan(app, scope="Saarbrücken")
    assert result.research == [] and result.research_pending >= 1 and n(app, "r_research") == 0


# ---------------------------------------------------------------- Provider
def test_prepared_providers_refuse_until_cleared(app, loaded):
    with pytest.raises(PolicyViolation) as exc:
        scan(app, scope="Saarbrücken", providers=["doctolib"])
    assert exc.value.code == "provider_disabled"
    app.policies.providers.doctolib = ProviderConfig(enabled=True)
    with pytest.raises(ProviderNotCleared) as exc:
        scan(app, scope="Saarbrücken", providers=["doctolib"])
    assert "tos_reviewed" in exc.value.message and "approved_by" in exc.value.message
    app.policies.providers.doctolib = ProviderConfig(enabled=True, clearance=Clearance(
        tos_reviewed=True, robots_checked=True, rate_limit_agreed=True, internal_policy_ok=True, approved_by="Tim"))
    with pytest.raises(ProviderNotAvailable):     # freigegeben, aber keine technische Zugriffsmethode
        scan(app, scope="Saarbrücken", providers=["doctolib"])
    app.policies.providers.map = ProviderConfig(enabled=True)
    with pytest.raises(ProviderNotAvailable):
        scan(app, scope="Saarbrücken", providers=["map"])
    with pytest.raises(ValidationFailed) as exc:
        scan(app, scope="Saarbrücken", providers=["google_maps"])
    assert exc.value.code == "unknown_provider"


def test_disabled_local_import_is_refused(app, scan_source):
    app.policies.providers.local_import = ProviderConfig(enabled=False)
    with pytest.raises(PolicyViolation) as exc:
        scan(app, scope="Saarbrücken", from_files=[scan_source])
    assert exc.value.code == "provider_disabled"


def test_cleared_doctolib_provider_plugs_in_with_provenance(app, loaded):
    from copilot.knowledge.records import PracticeRecord
    from copilot.scanner.providers.doctolib import DoctolibListing

    class FakeAccess:  # stellt eine künftige, erlaubte Zugriffsmethode dar – kein echter Abruf
        def search(self, query):
            yield DoctolibListing(PracticeRecord(name="SYNTH Doc Neu", street="Docweg 1", plz="66111", ort="Saarbrücken",
                                                 specialty_labels=["Hautarzt"]), "https://doctolib.invalid/praxis/synth-doc-neu")
            yield DoctolibListing(PracticeRecord(name="SYNTH Doc Zwei", street="Docweg 2", plz="66111", ort="Saarbrücken"),
                                  "https://doctolib.invalid/praxis/synth-doc-zwei")

    app.policies.providers.doctolib = ProviderConfig(enabled=True, clearance=Clearance(
        tos_reviewed=True, robots_checked=True, rate_limit_agreed=True, internal_policy_ok=True, approved_by="Tim"))
    app.scanner.doctolib_access_method = FakeAccess()
    result = scan(app, scope="Saarbrücken", providers=["doctolib"])
    assert result.ingest[0][0] == "doctolib" and result.ingest[0][1].created == 2
    doc = app.knowledge_repo.find_practice_by_key("synth doc neu|66111|docweg 1")
    fact, = app.research_repo.facts_for(EntityType.PRACTICE, doc.id)
    source = app.research_repo.get_source(fact.source_id)
    assert fact.key == "doctolib_profile_public" and source.source_type.value == "doctolib_public"
    assert source.url == "https://doctolib.invalid/praxis/synth-doc-neu" and "Tim" in source.tos_ref
    assert app.knowledge_repo.origins_of(doc.id)[0]["provider"] == "doctolib"
    reasons = {p.name: r for p, r in result.excluded}
    assert reasons["SYNTH Doc Neu"] == reasons["SYNTH Doc Zwei"] == "already_doctolib_recognised"   # belegtes Signal
    assert "SYNTH Doc Neu" not in by_name(result)


def test_doctolib_fetch_policy_only_via_cleared_provider(app):
    from copilot.scanner.providers.doctolib import DoctolibProvider
    research = ResearchPolicy(allowed_domains=["doctolib.de"])
    with pytest.raises(PolicyViolation) as exc:
        FetchPolicy(research).check_url("https://www.doctolib.de/")
    assert exc.value.code == "doctolib_not_cleared"
    with pytest.raises(PolicyViolation):
        DoctolibProvider(ProviderConfig(enabled=True)).fetch_policy(research)   # nicht freigegeben
    cleared = ProviderConfig(enabled=True, clearance=Clearance(tos_reviewed=True, robots_checked=True,
                             rate_limit_agreed=True, internal_policy_ok=True, approved_by="Tim"))
    policy = DoctolibProvider(cleared).fetch_policy(research)
    assert policy.check_url("https://www.doctolib.de/") == "www.doctolib.de"
    with pytest.raises(PolicyViolation) as exc:                                   # Domain muss zusätzlich freigegeben sein
        DoctolibProvider(cleared).fetch_policy(ResearchPolicy()).check_url("https://www.doctolib.de/")
    assert exc.value.code == "domain_not_allowed"
    with pytest.raises(PolicyViolation) as exc:                                   # LinkedIn nie
        policy.check_url("https://www.linkedin.com/in/x")
    assert exc.value.code == "hard_blocked_domain"


# ---------------------------------------------------------------- Ausgabe
def test_output_is_serialisable_and_complete(app, loaded, scan_source):
    from copilot.scanner.render import render_text
    result = scan(app, scope="Saarbrücken", radius_km=10, from_files=[scan_source], limit=3)
    data = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
    item = data["items"][0]
    for key in ("name", "specialties", "doctors", "distance", "origins", "status", "research_status", "doctolib_signal",
                "website", "facts", "network", "next_action", "score", "reasons", "unknowns"):
        assert key in item
    assert len(data["items"]) == 3 and data["area"]["accuracy"]
    text = render_text(result)
    for label in ("Genauigkeit:", "Entfernung:", "Quelle:", "Doctolib:", "Research:", "Nächste Aktion:", "Mögliche Dubletten"):
        assert label in text


def test_ranking_is_deterministic(app, loaded, scan_source):
    a = [(i.practice.id, i.worklist.score) for i in scan(app, scope="Saarbrücken", radius_km=10, dry_run=True).items]
    b = [(i.practice.id, i.worklist.score) for i in scan(app, scope="Saarbrücken", radius_km=10, dry_run=True).items]
    assert a == b


def test_practices_without_recorded_origin_say_so(app):
    from copilot.knowledge.records import PracticeRecord
    app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Ohne Herkunft", plz="66111", ort="Saarbrücken"))
    item = scan(app, scope="Saarbrücken").items[0]
    assert item.origins == ["unbekannt (kein Herkunftsnachweis gespeichert)"]      # nie eine Quelle erfinden
