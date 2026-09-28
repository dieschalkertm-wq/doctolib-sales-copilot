"""CLI (argparse, keine zusätzliche Abhängigkeit). Nur Level 1/2: lesen, strukturieren, vorschlagen.
Es gibt bewusst keinen Befehl mit externem Effekt (Mail, LinkedIn, CRM)."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from copilot import __version__
from copilot.app import App
from copilot.config import Settings
from copilot.connectors.imports.csv_practices import CsvPracticeSource
from copilot.connectors.imports.mapping import load_mapping
from copilot.connectors.imports.service import ROLES, PracticeImporter
from copilot.domain.enums import EntityType, RelationType
from copilot.domain.models import FactDraft
from copilot.errors import CopilotError, NotFound
from copilot.logging_setup import configure_logging
from copilot.research.client import PoliteClient
from copilot.research.policy import FetchPolicy
from copilot.research.practice_website import PracticeWebsiteProvider
from copilot.research.provider import ResearchRequest
from copilot.research.service import ResearchService
from copilot.research.transport import UrllibTransport
from copilot.storage.db import schema_version

log = logging.getLogger("copilot.cli")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="copilot", description="doctolib Sales Copilot (Level 1/2: Research & Vorschläge)")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="Datenbank anlegen/migrieren, Fachrichtungen einspielen")
    sub.add_parser("territory", help="Vertriebsgebiet anzeigen")
    sub.add_parser("specialties", help="Fachrichtungs-Katalog anzeigen")

    imp = sub.add_parser("import", help="Datenimport")
    imp_sub = imp.add_subparsers(dest="what", required=True)
    ip = imp_sub.add_parser("practices", help="Praxis-/Kundenliste (CSV/TSV) importieren")
    ip.add_argument("file", type=Path)
    ip.add_argument("--as", dest="role", choices=ROLES, default="practices",
                    help="practices=nur Stammdaten, customers=als Bestandskunden, prospects=als Prospects")
    ip.add_argument("--mapping", type=Path, help="YAML-Mapping für abweichende Spaltennamen")
    ip.add_argument("--encoding", default="auto")
    ip.add_argument("--delimiter", default="auto", help="auto, ';', ',', tab, '|'")
    ip.add_argument("--dry-run", action="store_true", help="prüfen, ohne zu schreiben")

    pr = sub.add_parser("practice", help="Praxen anzeigen").add_subparsers(dest="what", required=True)
    pl = pr.add_parser("list")
    pl.add_argument("--scope", help="Ort oder Region, z. B. Saarbrücken oder Vulkaneifel")
    ps = pr.add_parser("show")
    ps.add_argument("id", type=int)

    rs = sub.add_parser("research", help="Recherche (Policy-Gate aktiv)").add_subparsers(dest="what", required=True)
    rw = rs.add_parser("website", help="Praxis-Website analysieren (Domain muss in policies.yaml freigegeben sein)")
    rw.add_argument("--practice", type=int, required=True)
    rw.add_argument("--url", help="Standard: hinterlegte Website der Praxis")

    fc = sub.add_parser("fact", help="Facts erfassen").add_subparsers(dest="what", required=True)
    fa = fc.add_parser("add", help="Manuell belegten Fact erfassen (Quelle: manuelle Erfassung)")
    fa.add_argument("--practice", type=int, required=True)
    fa.add_argument("--key", required=True)
    fa.add_argument("--value", required=True, help="JSON oder Text")
    fa.add_argument("--note", help="Beleg/Kontext, z. B. 'Gespräch am …'")

    nw = sub.add_parser("network", help="Überweisernetzwerk").add_subparsers(dest="what", required=True)
    nd = nw.add_parser("derive", help="Regelbasiert ableiten (origin=derived, NICHT belegt)")
    nd.add_argument("--practice", type=int, required=True)
    nd.add_argument("--radius-km", type=float, default=25.0)
    no = nw.add_parser("observe", help="Belegte Beziehung (erfordert einen aktiven Fact)")
    no.add_argument("--from", dest="src", type=int, required=True)
    no.add_argument("--to", type=int, required=True)
    no.add_argument("--fact", type=int, required=True)
    nm = nw.add_parser("manual", help="Selbst erfasste Beziehung")
    nm.add_argument("--from", dest="src", type=int, required=True)
    nm.add_argument("--to", type=int, required=True)
    nm.add_argument("--note")
    nl = nw.add_parser("list")
    nl.add_argument("--practice", type=int, required=True)

    wl = sub.add_parser("worklist", help="Arbeitsliste für ein Gebiet, z. B. 'Saarbrücken'")
    wl.add_argument("scope")
    wl.add_argument("--limit", type=int)
    wl.add_argument("--save-scores", action="store_true", help="Scores in den Prospect-Datensätzen speichern")

    au = sub.add_parser("audit", help="Audit-Log anzeigen")
    au.add_argument("--limit", type=int, default=20)
    return p


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _practice_or_404(app: App, practice_id: int):
    practice = app.knowledge_repo.get_practice(practice_id)
    if practice is None:
        raise NotFound(f"Praxis {practice_id} nicht gefunden", code="practice_not_found")
    return practice


def _line(p) -> str:
    where = ", ".join(x for x in (f"{p.plz or ''} {p.ort or ''}".strip(), p.region) if x)
    return f"#{p.id:<4} {p.name}  [{where or 'kein Ort'}]"


def cmd_init(app: App, a) -> None:
    n = lambda t: app.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]  # noqa: E731
    print(f"Datenbank: {app.settings.db_path}\nSchema:    {schema_version(app.conn)}")
    print(f"Fachrichtungen: {n('k_specialty')} · Praxen: {n('k_practice')} · Facts: {n('r_fact')}")


def cmd_territory(app: App, a) -> None:
    for region in app.territory.regions.values():
        places = [pl.name for pl in app.territory.places if pl.region == region.key]
        print(f"{region.name} ({region.key}): {', '.join(places) or '-'}")


def cmd_specialties(app: App, a) -> None:
    for s in app.knowledge_repo.list_specialties():
        print(f"{s.code:<20} {s.name}")


def cmd_import(app: App, a) -> None:
    mapping = load_mapping(a.mapping)
    source = CsvPracticeSource(a.file, mapping, encoding=a.encoding, delimiter=a.delimiter)
    print("Erkannte Spalten: " + ", ".join(f"{k}←'{v}'" for k, v in source.column_map.items()))
    report = PracticeImporter(app.knowledge, app.pipeline, app.audit, app.conn).run(
        source, role=a.role, dry_run=a.dry_run)
    print(f"{'[DRY-RUN] ' if a.dry_run else ''}Zeilen: {report.rows} · neu: {report.created} · aktualisiert: {report.updated}"
          f" · unverändert: {report.unchanged} · fehlerhaft: {report.failed}")
    if report.role == "customers":
        print(f"Neue Kunden markiert: {report.customers_marked}")
    if report.role == "prospects":
        print(f"Neue Prospects: {report.prospects_created}")
    if report.warnings:
        print("Warnungen: " + ", ".join(f"{k}={v}" for k, v in sorted(report.warnings.items())))
    for issue in report.issues:
        print(f"  Zeile {issue.row}: {', '.join(issue.codes)}")


def cmd_practice(app: App, a) -> None:
    if a.what == "list":
        if a.scope:
            scope = app.territory.parse_scope(a.scope)
            if scope is None:
                raise NotFound(f"Unbekanntes Gebiet '{a.scope}'", code="unknown_scope")
            key = scope.place.region if scope.place else scope.region.key
            items = [p for p in app.knowledge_repo.list_practices(region=key)
                     if scope.place is None or app.territory.find_place(p.ort) == scope.place]
        else:
            items = app.knowledge_repo.list_practices()
        for p in items:
            print(_line(p))
        print(f"{len(items)} Praxen")
        return
    p = _practice_or_404(app, a.id)
    print(_line(p))
    print(f"Adresse: {p.street or '-'}, {p.plz or ''} {p.ort or ''}")
    print(f"Website (Stammdaten): {p.website_url or '-'}")
    print("Fachrichtung: " + (", ".join(s.name for s in app.knowledge_repo.practice_specialties(p.id)) or "unbekannt"))
    print("Ärzte: " + (", ".join(f"{d.title + ' ' if d.title else ''}{d.full_name}" for d in app.knowledge_repo.doctors_of(p.id)) or "nicht erfasst"))
    print("Kunde: " + ("ja" if app.pipeline_repo.get_customer(p.id) else "nein"))
    profile = app.facts.profile(EntityType.PRACTICE, p.id)
    print("\nBelegte Fakten (aktuell):" + ("" if profile.current else " keine"))
    for v in profile.current:
        print("  " + v.statement())
    if profile.stale:
        print("Veraltet:")
        for v in profile.stale:
            print("  " + v.statement())
    if profile.unknown_keys:
        print("Unbekannt / zu klären: " + ", ".join(profile.unknown_keys))
    rels = app.network_repo.for_entity(EntityType.PRACTICE, p.id)
    if rels:
        print("\nNetzwerk:")
        for r in rels:
            print(f"  #{r.from_id} → #{r.to_id} ({r.rel_type.value}): {app.network.describe(r)}")


def cmd_research(app: App, a) -> None:
    practice = _practice_or_404(app, a.practice)
    client = PoliteClient(FetchPolicy(app.policies.research), UrllibTransport(), app.settings.user_agent)
    service = ResearchService(app.conn, app.research_repo, app.facts, app.knowledge_repo, app.audit,
                              app.settings.raw_cache_dir)
    result = service.run(PracticeWebsiteProvider(client, app.policies),
                         ResearchRequest(EntityType.PRACTICE, practice.id, a.url or practice.website_url))
    print(f"Quelle #{result.source.id}: {result.source.url} (abgerufen {result.source.retrieved_at.isoformat()})")
    for fact in result.facts:
        print("  " + app.facts.view(fact).statement())
    if not result.facts:
        print("  keine belegbaren Signale gefunden (das ist KEIN Beleg für ein Fehlen).")


def cmd_fact(app: App, a) -> None:
    _practice_or_404(app, a.practice)
    fact = app.facts.record_manual(EntityType.PRACTICE, a.practice, FactDraft(key=a.key, value=_parse_value(a.value)),
                                   note=a.note)
    app.audit.record("fact.manual", "Fact manuell erfasst", entity_type="practice", entity_id=a.practice,
                     details={"fact_id": fact.id, "source_id": fact.source_id})
    print(f"Fact #{fact.id} gespeichert. " + app.facts.view(fact).statement())


def cmd_network(app: App, a) -> None:
    if a.what == "derive":
        r = app.network.derive_for_practice(a.practice, a.radius_km)
        app.audit.record("network.derive", "Beziehungen regelbasiert abgeleitet", entity_type="practice",
                         entity_id=a.practice, details={"created": r.created, "origin": "derived",
                                                        "radius_km": a.radius_km, "skipped_no_geo": r.skipped_no_geo})
        if r.no_specialty:
            print("Keine Regel anwendbar (Praxis hat keine Fachrichtung mit Überweiser-Regel).")
        print(f"Abgeleitet (NICHT belegt): neu {r.created}, bereits vorhanden {r.existing}, ohne Geodaten übersprungen {r.skipped_no_geo}")
    elif a.what in ("observe", "manual"):
        rel = (app.network.record_observed(a.src, a.to, a.fact) if a.what == "observe"
               else app.network.record_manual(a.src, a.to, a.note))
        app.audit.record(f"network.{a.what}", "Beziehung erfasst", entity_type="practice", entity_id=a.src,
                         details={"origin": rel.origin.value, "rel_type": rel.rel_type.value})
        print(f"Beziehung #{rel.id}: {app.network.describe(rel)}")
    else:
        _practice_or_404(app, a.practice)
        for r in app.network_repo.for_entity(EntityType.PRACTICE, a.practice):
            dist = f" {r.distance_km:g} km" if r.distance_km is not None else ""
            print(f"#{r.from_id} → #{r.to_id} {r.rel_type.value}{dist}: {app.network.describe(r)}")


def cmd_worklist(app: App, a) -> None:
    wl = app.worklist.build(a.scope, limit=a.limit)
    print(f"Arbeitsliste: {wl.scope_label} ({len(wl.items)} Praxen)")
    if wl.excluded:
        print("Ausgeschlossen: " + ", ".join(f"{k}={v}" for k, v in sorted(wl.excluded.items())))
    for n, item in enumerate(wl.items, start=1):
        print(f"\n{n}. {_line(item.practice)}  Score {item.score:g}  ({item.status}{', ' + item.stage if item.stage else ''})")
        for r in item.reasons:
            print(f"   +{r.points:g} {r.criterion}: {r.explanation}")
        for u in item.unknowns:
            print(f"   ? {u}")
        print(f"   → nächste Aktion: {item.next_action}")
        if a.save_scores and item.status == "prospect":
            app.pipeline_repo.save_score(item.practice.id, item.score,  # type: ignore[arg-type]
                                         [{"criterion": r.criterion, "points": r.points, "explanation": r.explanation}
                                          for r in item.reasons])


def cmd_audit(app: App, a) -> None:
    for r in app.audit.tail(a.limit):
        print(f"{r['occurred_at']} {r['actor']} {r['event_type']} {r['entity_type'] or ''}{r['entity_id'] or ''} {r['details']}")


COMMANDS = {"init": cmd_init, "territory": cmd_territory, "specialties": cmd_specialties, "import": cmd_import,
            "practice": cmd_practice, "research": cmd_research, "fact": cmd_fact, "network": cmd_network,
            "worklist": cmd_worklist, "audit": cmd_audit}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = Settings.from_env()
        configure_logging(settings.log_level)
        app = App.open(settings)
    except CopilotError as exc:
        print(f"Fehler [{exc.code}]: {exc.message}", file=sys.stderr)
        return exc.exit_code
    try:
        COMMANDS[args.cmd](app, args)
        return 0
    except CopilotError as exc:
        log.warning("command failed code=%s", exc.code)
        print(f"Fehler [{exc.code}]: {exc.message}", file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 – keine Details/Daten in die Ausgabe
        log.error("unexpected error type=%s", type(exc).__name__)
        print(f"Unerwarteter Fehler ({type(exc).__name__}). Details wurden aus Datenschutzgründen nicht ausgegeben.",
              file=sys.stderr)
        return 1
    finally:
        app.close()


if __name__ == "__main__":
    raise SystemExit(main())
