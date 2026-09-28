"""Lesbare Text-Ausgabe des Scans. Rein darstellend – dieselben Daten liefert `ScanResult.to_dict()` für eine spätere UI."""

from __future__ import annotations

from copilot.scanner.result import ScanItem, ScanResult

REASONS = {
    "customer": "Bestandskunde",
    "already_doctolib_recognised": "doctolib bereits erkennbar (belegt)",
    "already_worked": "bereits bearbeitet (--unworked)",
}
_PROVIDER_STATUS = {"researched": "recherchiert", "blocked": "blockiert", "failed": "fehlgeschlagen"}


def _reason(code: str) -> str:
    return REASONS.get(code) or (f"Pipeline-Status {code[6:]}" if code.startswith("stage_") else code)


def _item(n: int, item: ScanItem, dry_run: bool) -> list[str]:
    p = item.practice
    ident = "#(neu)" if dry_run and item.is_new else f"#{p.id}"   # im Dry-Run wird die ID zurückgerollt
    where = f"{p.plz or ''} {p.ort or ''}".strip() or "kein Ort"
    lines = [f"\n{n:>2}. {ident} {p.name}{'  [NEU]' if item.is_new else ''}",
             f"    {', '.join(item.specialties) or 'Fachrichtung unbekannt'} · {where}"
             + (f" · {p.street}" if p.street else ""),
             f"    Entfernung: {item.distance}",
             f"    Quelle: {'; '.join(item.origins)}",
             f"    Status: {'Prospect (' + item.stage + ')' if item.status == 'prospect' else 'noch nicht erfasst'}"
             f" · Research: {item.research_status}",
             f"    Doctolib: {item.doctolib_signal}",
             f"    Website: {item.website or 'unbekannt'}"]
    if item.doctors:
        lines.append(f"    Ärzte: {', '.join(item.doctors)}")
    lines.append(f"    Score {item.worklist.score:g}: "
                 + ("; ".join(f"+{r.points:g} {r.criterion} ({r.explanation})" for r in item.worklist.reasons) or "keine Punkte"))
    for rel in item.network:
        lines.append(f"    Netzwerk: {rel}")
    for fact in item.facts:
        lines.append(f"    Fact: {fact}")
    fact_keys = [u.split("'")[1] for u in item.worklist.unknowns if u.startswith("Fact '")]
    others = [u for u in item.worklist.unknowns if not u.startswith("Fact '")]
    if fact_keys or others:
        lines.append("    Unbekannt / zu klären: " + ", ".join(others + fact_keys))
    lines.append(f"    → Nächste Aktion: {item.next_action_text}")
    return lines


def render_text(result: ScanResult) -> str:
    out = ["=" * 78, f"Territory Scan: {result.area_label}" + ("   [DRY-RUN – nichts gespeichert]" if result.dry_run else ""),
           "=" * 78, f"Gebiet:      {result.area_description}"]
    out += [f"Genauigkeit: {note}" for note in result.accuracy_notes]

    for name, rep, rejected in result.ingest:
        out.append(f"Quelle {name}: {rep.seen} Kandidaten · neu {rep.created} · angehängt {rep.attached} · "
                   f"Merge-Queue {rep.queued} (bereits eingereiht {rep.already_queued}) · "
                   f"außerhalb Gebiet {rep.skipped_outside} · ohne Geodaten {rep.skipped_no_geo} · "
                   f"andere Fachrichtung {rep.skipped_specialty}"
                   + (f" · fehlerhafte Zeilen {len(rejected)}" if rejected else ""))
        for row, codes in rejected:
            out.append(f"   Zeile {row}: {', '.join(codes)}")

    inside = sum(1 for i in result.items if i.match and i.match.certainty.value == "inside")
    possible = sum(1 for i in result.items if i.match and i.match.certainty.value == "possible")
    counts = f"{len(result.items)} Praxen"
    if possible:
        counts += f" ({inside} sicher im Gebiet, {possible} möglicherweise)"
    out.append(f"\nArbeitsliste „{result.area_label} – heute“: {counts}")
    if result.excluded:
        out.append(f"Ausgeschlossen ({len(result.excluded)}): "
                   + ", ".join(f"#{p.id} {p.name} – {_reason(r)}" for p, r in result.excluded))
    if result.no_geo:
        out.append(f"Hinweis: {result.no_geo} Praxen im Vertriebsgebiet ohne Geodaten – im Radius nicht prüfbar.")
    if result.dropped_uncertain:
        out.append(f"Hinweis: {result.dropped_uncertain} 'möglicherweise'-Treffer wegen --strict-radius ausgeblendet.")
    if result.skipped_specialty:
        out.append(f"Hinweis: {result.skipped_specialty} Praxen im Gebiet mit anderer/unbekannter Fachrichtung ausgeblendet.")

    for n, item in enumerate(result.items, start=1):
        out += _item(n, item, result.dry_run)

    queue = [(name, q) for name, rep, _ in result.ingest for q in rep.queue]
    if queue:
        out.append("\nMögliche Dubletten – bitte prüfen (nichts wurde zusammengeführt; siehe: copilot merge list):")
        for name, q in queue:
            out.append(f"  Merge #{q.merge_id}: „{q.candidate_name}“ ↔ Praxis #{q.practice_id} "
                       f"(Confidence {q.confidence:.2f}: {', '.join(q.reasons)}){'' if q.new else ' [bereits eingereiht]'}")
    if result.research:
        out.append("\nWebsite-Research:")
        for o in result.research:
            out.append(f"  Praxis #{o.practice_id}: {_PROVIDER_STATUS.get(o.status, o.status)} ({o.detail})")
    elif result.research_pending:
        out.append(f"\nRecherche möglich für {result.research_pending} Praxen mit Website: "
                   "erneut mit --research ausführen (nur freigegebene Domains, robots.txt, Rate-Limit).")
    n = result.network
    if n.created or n.existing:
        out.append(f"Netzwerk: {n.created} neue abgeleitete Beziehungen (nicht belegt), {n.existing} bereits vorhanden.")
    if not result.items:
        out.append("\n(Keine Treffer. Tipp: Daten importieren oder --from-file DATEI angeben.)")
    return "\n".join(out)
