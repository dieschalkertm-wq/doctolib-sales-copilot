# doctolib Sales Copilot

Persönlicher Sales-Intelligence-Copilot (lokal-first) für das Gebiet Saarland · Trier · Wittlich · Vulkaneifel.
Architektur und Begründungen: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Stand: Phase 0 (Fundament) + Phase 1 (Territory & Knowledge) + Territory Scanner.** Es gibt bewusst keine externen
Aktionen (Mail, LinkedIn, CRM) und keinen produktiven doctolib-/LinkedIn-Abruf. Alle Befehle liegen auf
Automatisierungsstufe 1/2 (Research & Vorschläge). Der Copilot ist eine Automatisierungsschicht über deinem Workflow,
kein zweites CRM: [`docs/TERRITORY_SCANNER.md`](docs/TERRITORY_SCANNER.md).

## Lokal starten

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # Abhängigkeiten: pydantic, pyyaml (+ pytest)
cp .env.example .env             # optional; .env ist gitignored
copilot init                     # legt data/copilot.sqlite3 an, migriert, spielt Fachrichtungen ein
pytest                           # Testlauf (kein Netzwerkzugriff)
```

Der Befehl läuft im Repo-Verzeichnis (dort liegen `config/` und `data/`); von anderswo `COPILOT_HOME=/pfad/zum/repo` setzen.

| Befehl | Zweck |
|---|---|
| `copilot territory` / `specialties` | Gebiet bzw. Fachrichtungs-Katalog anzeigen |
| `copilot import practices DATEI [--as practices\|customers\|prospects] [--mapping m.yaml] [--dry-run]` | Praxis-/Kundenliste importieren |
| `copilot practice list [--scope Saarbrücken]` / `practice show ID` | Praxen; `show` trennt belegte Fakten, veraltete und „Unbekannt / zu klären“ |
| `copilot worklist Saarbrücken [--limit N] [--save-scores]` | Deterministische Arbeitsliste mit Punktbegründung und nächster Aktion |
| `copilot network derive --practice ID` | Überweiser **regelbasiert ableiten** (`derived`, nicht belegt) |
| `copilot fact add --practice ID --key K --value V --note …` | Belegten Fact manuell erfassen (Quelle „manuelle Erfassung“) |
| `copilot network observe --from A --to B --fact F` | Beziehung als `observed` – nur mit aktivem Fact |
| `copilot research website --practice ID [--url URL]` | Praxis-Website analysieren (nur freigegebene Domains, robots.txt, Rate-Limit) |
| `copilot territory scan ORT [--radius KM] [--specialty S]… [--from-file DATEI] [--around-customers] [--unworked] [--research] [--dry-run] [--json]` | **Territory Scan** → Arbeitsliste (siehe unten) |
| `copilot territory scan --around-practice ID --radius KM` | Umkreis um eine Praxis |
| `copilot providers` | Datenquellen-Provider: was läuft, was ist nur vorbereitet |
| `copilot merge list` / `merge resolve ID --same\|--different` | Merge-Queue für mögliche Dubletten (nie automatisch) |
| `copilot audit` | Audit-Log |

## Synthetische Testdaten importieren

`tests/fixtures/synthetic_practices.txt` enthält ausschließlich erfundene Daten (`SYNTH …`, Domains `.invalid`).
Die Endung `.txt` ist Absicht: `*.csv` ist in `.gitignore` gesperrt. Der Importer erkennt Trennzeichen und Kodierung selbst.

```bash
copilot import practices tests/fixtures/synthetic_practices.txt --dry-run   # prüfen, nichts schreiben
copilot import practices tests/fixtures/synthetic_practices.txt             # importieren (idempotent)
copilot worklist Saarbrücken
copilot practice show 1
copilot network derive --practice 1 && copilot network list --practice 1
```

Nutze für die Fixture eine Wegwerf-DB (`COPILOT_DATA_DIR=/tmp/copilot-test copilot …`), damit sich Testdaten nicht mit
echten Daten mischen.

## Territory Scan

```bash
copilot territory scan saarbrücken                              # „Bearbeite Saarbrücken“ (Zuordnung nach Ortsangabe)
copilot territory scan saarbrücken --radius 10                  # 10 km um den Ortsmittelpunkt (mit Genauigkeitsangabe)
copilot territory scan saarbrücken --specialty orthopaedie      # Fachrichtungen über den Katalog (Aliasse ok), mehrfach möglich
copilot territory scan saarbrücken --around-customers --radius 10 --unworked
                                                                # relevante Fachärzte im Umfeld meiner Hausarztkunden, noch nicht bearbeitet
copilot territory scan saarbrücken --from-file export.csv --dry-run   # eigene Liste als Quelle, Vorschau ohne Speichern
copilot territory scan saarbrücken --research                   # zusätzlich Website-Research (nur freigegebene Domains, gedeckelt)
copilot merge list                                              # mögliche Dubletten prüfen
```

Mit den synthetischen Fixtures (Wegwerf-DB!):

```bash
export COPILOT_DATA_DIR=/tmp/copilot-demo
copilot import practices tests/fixtures/synthetic_practices.txt
copilot territory scan saarbrücken --radius 10 --from-file tests/fixtures/synthetic_scan_source.txt --dry-run
```

Die Arbeitsliste zeigt je Praxis Fachrichtung, Ort, Entfernung (Näherungen als „≈ … (±5 km)“), Quelle, Status,
Research-Status, belegtes Doctolib-Signal, Website, Facts, Netzwerkbezug (`derived` = „nicht belegt“) und die nächste Aktion.

### Was heute funktioniert – und was nur vorbereitet ist

| Quelle / Baustein | Status |
|---|---|
| Eigene Listen/Exporte (`--from-file`, `import practices`) | **funktioniert** |
| Praxis-Websites (Research, `--research`) | **funktioniert** (Domain-Freigabe nötig, robots.txt, Rate-Limit, gedeckelt) |
| Matching gegen Bestand + Merge-Queue | **funktioniert** (konservativ, kein automatisches Fuzzy-Merging) |
| Radius-/Gebietslogik mit Unsicherheit | **funktioniert** (Genauigkeit: Ortsmittelpunkte ±5 km, exakte Koordinaten wenn geliefert) |
| Karten-/Geodaten (`map`) | vorbereitet (Interface, keine Datenquelle) |
| Doctolib (`doctolib`) | vorbereitet (Freigabe-Checkliste + Provider-Interface, keine Zugriffsmethode) |
| LLM-Gateway | vorbereitet (aus, kein Anbieter) |

## Echte Datenquellen anschließen

1. **Eigene Kunden-/Praxislisten (CSV/TSV/Excel-Export als CSV)** – funktioniert schon jetzt:
   Datei nach `data/imports/` legen (gitignored), `copilot import practices data/imports/datei.csv --dry-run`.
   Kopfzeilen werden über Aliasse erkannt (Praxisname/Name/Account Name, Straße, PLZ, Ort, „PLZ Ort“, Fachrichtung,
   Website, Ärzte, …). Abweichende Exporte über eine Mapping-Datei:
   ```yaml
   columns: {name: "Einrichtungsbezeichnung", ort: "Sitz", plz: "Postleitzahl"}
   ```
   Der Import füllt nur Lücken und überschreibt bestehende Werte nie. Fehler-/Warnberichte enthalten nur
   Zeilennummer + Code (`missing_name`, `invalid_plz`, `unknown_specialty`, `outside_territory`, …).
2. **Weitere Quellen (CRM-Export, Registry, …)**: Adapter in `src/copilot/connectors/` schreiben, der das
   Protocol `PracticeSource` (`connectors/base.py`) erfüllt und `PracticeRecord`s liefert. Import-, Knowledge- und
   Audit-Logik bleiben unverändert.
3. **Web-Research**: neuer `ResearchProvider` in `src/copilot/research/` (Vorlage: `practice_website.py`). Provider liefern
   nur Source- und Fact-Entwürfe; Persistenz, Zeitstempel, `stale_after` und Supersede übernimmt der `ResearchService`.
   Domains müssen in `config/policies.yaml` (`research.allowed_domains`) freigegeben werden – Standard: **alles gesperrt**.
   `linkedin.com` ist immer gesperrt. `doctolib.*` ist für alle Provider gesperrt, außer für den `DoctolibProvider` nach
   vollständiger Freigabe-Checkliste (`providers.doctolib.clearance` in `config/policies.yaml`) – siehe
   [`docs/TERRITORY_SCANNER.md`](docs/TERRITORY_SCANNER.md). Neue Quellen: `SourceProvider` in `src/copilot/scanner/providers/`.
4. **Fachrichtungen / Überweiser-Regeln / Gewichte**: `config/specialties.yaml`, `config/referral_rules.yaml`,
   `config/scoring.yaml`, `config/territory.yaml` (alles ohne Secrets, committbar).

## Sicherheit

* `.gitignore` sperrt `.env*`, `data/`, `*.sqlite*`, `*.csv`, `*.xlsx`, Exporte, Logs, Schlüssel. Tests prüfen das.
* Secrets nur über Umgebung/`.env`; Konfig-Dateien mit secret-artigen Schlüsseln werden abgelehnt.
* Logs: Redaction von Mail/Telefon/Tokens, keine Tracebacks; Audit-Log per Allowlist (nur IDs/Zähler), append-only (DB-Trigger).
* DB-Datei/Ordner `0600`/`0700` (nur bei selbst angelegten Ordnern).
* Rohdaten von Websites liegen lokal in `data/raw_cache/` (0600) und dienen dem Nachprüfen der Facts.

## Schichten (siehe Architektur §5)

| Schicht | Tabellen | Regel |
|---|---|---|
| K Knowledge | `k_practice`, `k_doctor`, `k_specialty`, `k_network_relationship`, Verknüpfungen | dauerhaft, **keine** Rechercheergebnisse |
| R Research | `r_source`, `r_research`, `r_fact`, `r_event` | append-only; Fact ohne Quelle unmöglich; Claims unveränderlich, `stale_after` |
| P Pipeline | `p_customer`, `p_prospect` | Vertriebsstatus, getrennt von Fakten |
| A Audit | `a_audit_event` | append-only |

Erzwungen auch in der Datenbank: `observed` braucht `fact_id`, `derived` braucht `rule_id`, Fact braucht `source_id`.

## Entscheidungen zur Umsetzung (Architektur §3 ließ den Stack offen)

* Python ≥ 3.11 (Umgebung liefert 3.11), **stdlib `sqlite3` + versionierte SQL-Migrationen** (Prüfsummen) statt SQLAlchemy/Alembic,
  **argparse** statt Typer: weniger Abhängigkeiten. Repository-Schicht bleibt die Naht für einen späteren Wechsel auf PostgreSQL.
* Abhängigkeiten: nur `pydantic` (Validierung) und `pyyaml` (Konfig).

## Offene Punkte / bewusst noch nicht umgesetzt

* `Contact` (PII-Hotspot), `Action`, `FollowUp`, `Approval` und der Freigabe-Workflow (Phase 3/4); `Event` hat Tabellen/Repository, aber noch keine Erfassung/CLI.
* Kein LLM-Anbieter, keine Entwürfe (Phase 2; das Gateway ist vorbereitet), kein Gmail/Kalender/CRM/LinkedIn, kein doctolib-Abruf
  (Provider vorbereitet), kein Karten-Provider, keine Web-UI.
* Entity-Resolution: nur konservativ (siehe Scanner-Doku). Praxisgeodaten sind ohne exakte Koordinaten nur Ortsmittelpunkte
  (`geo_precision=place`, ±5 km Annahme) – Distanzen sind Näherungen. Vor Migration 0006 importierte Praxen haben keinen Herkunftsnachweis.
* Retention-Job für `raw_cache`, Lösch-/Auskunftsfunktion je Person.
* Scoring-Gewichte sind neutrale Platzhalter; Überweiser-Regeln sind eine Arbeitsannahme.
* Abzuklären (Architektur §13): interne KI-/Datenrichtlinie, erlaubte Datenquellen, doctolib-Arztsuche, UWG §7 für Mail.
