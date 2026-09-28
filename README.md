# doctolib Sales Copilot

Persönlicher Sales-Intelligence-Copilot (lokal-first) für das Gebiet Saarland · Trier · Wittlich · Vulkaneifel.
Architektur und Begründungen: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

**Stand: Phase 0 (Fundament) + Phase 1 (Territory & Knowledge).** Es gibt bewusst keine externen Aktionen
(Mail, LinkedIn, CRM) und keinen doctolib-/LinkedIn-Abruf. Alle Befehle liegen auf Automatisierungsstufe 1/2
(Research & Vorschläge).

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
   `doctolib.*` und `linkedin.com` sind zusätzlich im Code hart gesperrt (`research/policy.py`) und werden erst nach
   ausdrücklicher Freigabe/Klärung (Architektur §13) geöffnet.
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
* Kein LLM, keine Entwürfe (Phase 2), kein Gmail/Kalender/CRM/LinkedIn, kein doctolib-Abruf, keine Web-UI.
* Entity-Resolution: gleiche Praxis mit abweichender Schreibweise von Name/Straße/PLZ wird als neue Praxis angelegt
  (Merge-Queue folgt); Praxisgeodaten sind nur Ortsmittelpunkte (`geo_precision=place`) – Distanzen sind Näherungen.
* Retention-Job für `raw_cache`, Lösch-/Auskunftsfunktion je Person.
* Scoring-Gewichte sind neutrale Platzhalter; Überweiser-Regeln sind eine Arbeitsannahme.
* Abzuklären (Architektur §13): interne KI-/Datenrichtlinie, erlaubte Datenquellen, doctolib-Arztsuche, UWG §7 für Mail.
