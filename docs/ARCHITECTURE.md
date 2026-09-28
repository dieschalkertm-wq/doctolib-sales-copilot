# doctolib Sales Copilot – Architektur- & Umsetzungsanalyse

Status: **Entwurf zur Freigabe** (keine Implementierung). Stand: 2026-09-28.
Gebiet: Saarland, Trier, Wittlich, Vulkaneifel. Rolle: Account Executive.

---

## 1. Repository-Analyse

Leeres Repo (keine Commits, keine Dateien). Greenfield, keine Altlasten, keine Abhängigkeit zu „Die Schalker“. Angelegt wurden nur `.gitignore` (Secrets, Datenbanken, Exporte, CSV/XLSX, Logs ausgeschlossen) und dieses Dokument.

## 2. Strukturierte Anforderungen

| # | Bereich | Kernanforderung | Automatisierungs-Ziel |
|---|---|---|---|
| 1 | Territory Intelligence | Gebiet in Regionen/Orte gliedern, Praxen erfassen, priorisieren | L1–L2 |
| 2 | Praxis-/Ärzte-Recherche | Strukturiertes Profil mit Quellen, Lücken explizit („unbekannt“) | L1 |
| 3 | Überweisernetzwerk | Graph: Hausarzt → Fachrichtungen → Praxen → Kunde/Prospect | L1–L2 |
| 4 | Outbound-Vorbereitung | „Heute Saarbrücken“ → Arbeitsliste + nächste Aktion | L2 |
| 5 | E-Mail | Entwurf; Versand nur nach Freigabe | L2 → L3 |
| 6 | LinkedIn | Profil-Zuordnung, Nachrichtenentwürfe, kein Massenversand | L1–L2 |
| 7 | Events | Kongresse/Fortbildungen/Messen erfassen, Entfernung, Fristen | L1 |
| 8 | Meeting-Vorbereitung | Briefing nur aus vorhandenen, belegten Daten | L2 |
| 9 | Einwandbehandlung | Kontextbezogener Coach (Klassifikation, Rückfrage, nächster Schritt) | L2 |
| 10 | Follow-ups | Fälligkeiten, Entwürfe | L2 → L3 |
| 11 | Tagespriorisierung | „Was sollte ich heute tun?“ | L2 |
| 12 | Automatisierung | Stufenweise, nur mit Freigabe/Absicherung | L3–L4 |

**Querschnittsregeln (nicht verhandelbar):**
1. **Keine erfundenen Fakten.** Jede Aussage in Briefings/Mails referenziert einen Fakt mit Quelle. Was fehlt, steht als „Unbekannt / zu klären“.
2. **Kein externer Effekt ohne Freigabe** (E-Mail, LinkedIn, Kalender, CRM-Schreibzugriff).
3. **Secrets und echte Daten nie in Git.**
4. **Quellen + Zeitstempel für jede externe Information.**

## 3. Gesamtarchitektur

Empfehlung: **lokal-first Modularer Monolith**, ein Prozess, klare Modulgrenzen. Kein Microservice-Overhead für einen Einzelnutzer.

```
                ┌─────────────────────────────────────────────┐
                │  Interfaces: CLI (Phase 1) → Web-UI (später) │
                └──────────────────────┬──────────────────────┘
                                       │
                ┌──────────────────────▼──────────────────────┐
                │  Copilot / Orchestrierung (LLM-Schicht)      │
                │  Briefing · Outreach-Drafts · Coach · Daily  │
                │  – arbeitet NUR auf strukturierten Fakten –  │
                └───┬──────────┬───────────┬───────────┬──────┘
                    │          │           │           │
          ┌─────────▼─┐ ┌──────▼────┐ ┌────▼─────┐ ┌───▼────────┐
          │ Knowledge │ │ Pipeline  │ │ Actions  │ │ Research   │
          │ (stabil)  │ │ (Vertrieb)│ │ + Approval│ │ (zeitabh.) │
          └─────┬─────┘ └─────┬─────┘ └────┬─────┘ └───┬────────┘
                └─────────────┴─────┬──────┴───────────┘
                                    │
                        ┌───────────▼────────────┐
                        │ Storage (SQLite→PG)     │
                        │ + Audit-Log + Source-Reg│
                        └───────────▲────────────┘
                                    │
                ┌───────────────────┴────────────────────┐
                │ Connectors (Adapter-Interface, jeweils  │
                │ mit Policy-Check): Web, Import, Gmail,  │
                │ Kalender, Events, LinkedIn, CRM         │
                └─────────────────────────────────────────┘
```

**Stack-Vorschlag** (Entscheidung offen, siehe §14): Python 3.12, Pydantic (Validierung), SQLAlchemy + Alembic, SQLite (WAL) zum Start, Typer-CLI, später FastAPI + schlanke Web-UI. LLM über Anthropic API, hinter einem dünnen Interface (austauschbar, testbar mit Fake-Provider).

**Wichtiges Designprinzip – „Fakten vor Text“:** Das LLM bekommt nie freie Websuche als Wahrheitsquelle. Pipeline: Connector → Extraktion → **Fact mit Source** → erst dann Generierung. Der Generator bekommt eine Faktenliste mit IDs und muss beim Output Fakt-IDs mitliefern; ein Validator lehnt Behauptungen ohne Fakt-Referenz ab (Anti-Halluzination).

## 4. Ordnerstruktur (Vorschlag)

```
doctolib-sales-copilot/
├── docs/                    # Architektur, ADRs, Compliance-Checkliste
├── src/copilot/
│   ├── domain/              # Entitäten, Enums, Regeln (kein I/O)
│   ├── storage/             # Repositories, Migrationen
│   ├── research/            # Pipeline: fetch → extract → fact → source
│   ├── connectors/          # web/, imports/, gmail/, calendar/, events/, linkedin/, crm/
│   ├── knowledge/           # Netzwerkgraph, Fachrichtungs-Ontologie
│   ├── pipeline/            # Scoring, Priorisierung, Follow-ups
│   ├── actions/             # Action-Queue, Approval, Executor, Policies
│   ├── copilot/             # Briefing, Outreach, Coach, Daily
│   ├── llm/                 # Provider-Interface, Prompts, Fakt-Validator
│   ├── security/            # Secrets, PII-Redaction, Retention
│   └── cli/
├── config/                  # policies.yaml, scoring.yaml, playbooks (ohne Secrets)
├── tests/
├── data/                    # GITIGNORED: DB, Cache, Exporte
├── .env.example             # nur Platzhalter
└── .gitignore
```

## 5. Datenmodell

Vier strikt getrennte **Schichten** (eigene Tabellen-Präfixe/Schemas):

| Schicht | Inhalt | Änderbarkeit |
|---|---|---|
| **K – Knowledge** (dauerhaft) | Practice, Doctor, Specialty, Location, Beziehungen | selten, versioniert |
| **R – Research** (zeitabhängig) | Source, Research, Fact | append-only, mit `retrieved_at`, `valid_until` |
| **P – Pipeline** (Vertrieb) | Customer, Prospect, Contact, Opportunity-Status | laufend, durch Nutzer |
| **A – Actions** | Action, FollowUp, Approval, AuditEvent | Workflow-Zustände |

### Entitäten

**K – Knowledge**
- `Specialty` (id, code, name, parent_id, `refers_to[]`-Kandidaten) – z. B. Allgemeinmedizin, Kardiologie, Orthopädie …
- `Practice` (id, name, address, plz, ort, geo lat/lon, region[Saarland/Trier/Wittlich/Vulkaneifel], website_url, canonical_key)
- `Doctor` (id, name, titel, practice_id[n:m via `Practice_Doctor`], specialty_id[n:m])
- `NetworkRelationship` (id, from_entity, to_entity, type[`refers_to`|`same_practice`|`shared_location`|`colleague`], strength, origin[`derived`|`observed`|`manual`], fact_id?) – *derived* (Regel: Hausarzt→Fach) klar getrennt von *observed* (belegt).

**R – Research (zeitabhängig)**
- `Source` (id, type[`practice_website`|`doctolib_public`|`event_page`|`registry`|`manual`|`linkedin_manual`], url, publisher, `retrieved_at`, `published_at?`, `content_hash`, `robots_status`, `tos_ref`, `reliability`[1–5], `raw_ref`)
- `Research` (id, subject_type/id, kind, started_at, status, method)
- `Fact` (id, subject_type/id, key[z. B. `online_booking`, `website_url`, `uses_doctolib`], value, `source_id`, `confidence`, `observed_at`, `stale_after`, `superseded_by`) → Grundlage für „veraltet“-Erkennung.
- `Event` (id, name, date_from/to, ort, geo, specialty_targets[], url, registration_deadline, `distance_km`, source_id, exhibitors[] als Facts)

**P – Pipeline**
- `Customer` (id, practice_id, since, products[], notes) – Bestandskunde
- `Prospect` (id, practice_id, stage[`identified`→`researched`→`contacted`→`meeting`→`proposal`→`won/lost/parked`], score, score_reasons[], owner_notes, reason_lost)
- `Contact` (id, doctor_id?/name, role, email?, phone?, linkedin_url?, `consent_basis`, `data_origin`, `source_id`) – **PII-Hotspot**

**A – Actions**
- `Action` (id, type[`email_draft`|`linkedin_msg`|`call`|`research`|`meeting_prep`], target, payload, `level`[1–4], status[`draft`→`pending_approval`→`approved`→`executed`|`rejected`|`failed`], created_by[`copilot`|`user`], approved_at, executed_at)
- `FollowUp` (id, prospect_id, due_at, reason, action_id?, status)
- `Approval` / `AuditEvent` (wer, was, wann, Hash des freigegebenen Inhalts) – append-only.

**Trennungsregel:** Ein `Prospect`-Feld enthält *nie* Recherchewerte; Recherchewerte leben nur als `Fact` mit Source. Ansichten (Briefing) joinen zur Laufzeit. So bleibt erkennbar, was Fakt, was Einschätzung, was Vertriebsstatus ist.

## 6. Speicherstrategie

- **Phase 1:** SQLite (WAL), lokale Datei unter `data/`, ein Nutzer, keine Serverkosten, leicht sicherbar (Volume-Verschlüsselung, siehe §10).
- **Rohdaten-Cache** (HTML/Text der Quellen) getrennt von der DB, mit Retention (z. B. 90 Tage), damit Fakten nachprüfbar bleiben, aber PII nicht ewig liegt.
- **Netzwerkgraph:** als relationale Kanten (`NetworkRelationship`) + Abfragen per Recursive CTE. Eine Graph-DB ist bei tausenden Knoten überdimensioniert.
- **Migration später:** PostgreSQL (z. B. wenn Web-Hosting/Mehrnutzer nötig). Repository-Schicht hält das austauschbar.
- **Backup:** verschlüsselt, außerhalb des Repos.
- **Wichtig:** Ob echte Kundendaten außerhalb doctolib-Systemen liegen dürfen, ist eine **interne Compliance-Frage** (§13).

## 7. Web-Research-Architektur

```
Research-Job (Region/Ort/Fachrichtung/Praxis)
  → Policy-Gate (robots.txt, ToS-Freigabe je Quelle, Rate-Limit, Allowlist)
  → Fetcher (höflich: eigener User-Agent, 1 req/Domäne/Sek., Cache, Conditional GET)
  → Extractor (deterministisch: Schema.org/JSON-LD, Impressum, Kontaktseite; LLM nur als Fallback mit Zitatpflicht)
  → Normalizer (Adresse, Fachrichtung, Dedupe über canonical_key)
  → Fact + Source persistieren (retrieved_at, content_hash)
  → Staleness-Job (stale_after → „neu prüfen“)
```

Leitlinien:
- **Bevorzugte Quellen:** Praxis-Websites (Impressum/Kontakt/Team), Ärztekammer-/KV-Verzeichnisse (Nutzungsbedingungen prüfen!), Event-Seiten, manuelle Einträge/Importe.
- **doctolib-öffentliche Arztsuche:** *Kein* Scraping in Phase 1. Zuerst klären: ToS, robots.txt, interne Richtlinie (§13). Alternativen mit echtem Nutzen ohne Scraping: (a) interne doctolib-Daten/Exporte, die du legitim nutzen darfst, (b) manuelle Einzelprüfung mit Erfassung per CLI („Praxis X: doctolib-Profil ja/nein, Link“), (c) Praxis-Website enthält doctolib-Widget/Link → als Fakt erkennbar.
- Bei Extraktion erkennt das System „doctolib-Nutzer“ nur aus belegten Signalen (Link, Widget), nie geraten.
- Jede Quelle hat `robots_status` und Freigabe-Flag in `config/policies.yaml`; unbekannte Domains sind gesperrt, bis freigegeben.

## 8. Integrationen

| Integration | Nutzen | Wann | Hinweis |
|---|---|---|---|
| CSV/XLSX-Import (Bestandskunden, Territory-Listen) | Sofort echte Daten | **Phase 1** | interne Daten nur lokal, gitignored |
| Praxis-Websites (Impressum/Team) | Fakten | **Phase 1–2** | robots.txt, Rate-Limit |
| Manuelle Erfassung / CLI | Lücken füllen | **Phase 1** | Quelle „manual“ |
| LLM (Anthropic API) | Briefing, Drafts, Coach | **Phase 2** | nur minimierte Daten senden, Klärung Datenweitergabe |
| Events (öffentliche Kalender, Fachgesellschaften) | Event-Radar | Phase 3 | Quellen einzeln prüfen |
| Gmail (Entwürfe erstellen, *nicht* senden) | Draft-Workflow | Phase 3 | wäre über bestehenden Gmail-Connector in *deinem* Account möglich; Firmen-Mail eventuell IT-gesperrt |
| Kalender | Termine, Prep-Trigger | Phase 3 | read-only zuerst |
| CRM (vermutlich Salesforce) | Sync Status | Phase 4+ | Zugriff/Policy klären; ggf. nur Export/Import |
| LinkedIn | Recherche manuell + Drafts | Phase 2 (manuell), Automatisierung ggf. nie | Kein Scraping/Auto-Messaging (ToS-Verstoß, Kontosperre); nur offizielle APIs oder von dir manuell eingefügte Profildaten |
| doctolib-Arztsuche | Nutzer-Erkennung | erst nach Freigabe | siehe §7 |
| Automatisierung (Zapier o. Ä.) | Trigger | Phase 4 | nur für L4-freigegebene Aktionen |

## 9. Automatisierungsstufen

| Level | Bedeutung | Beispiele | Regel |
|---|---|---|---|
| **L1 Research** | lesen, strukturieren | Praxisprofil, Event-Liste | nur erlaubte Quellen, alles mit Source |
| **L2 Suggestion** | Vorschläge, Entwürfe, Priorisierung | Mail-Draft, Tagesplan, Briefing | rein intern, kein externer Effekt |
| **L3 Approval** | externe Aktion nach Freigabe | Mail senden, LinkedIn-Nachricht, Kalendereintrag | Action `pending_approval`; Freigabe bindet an Content-Hash; Änderung ⇒ neue Freigabe |
| **L4 Execution** | automatisch, nur wenn explizit erlaubt | z. B. interne Erinnerungen, Follow-up-Task anlegen | Whitelist in `policies.yaml` je Aktionstyp, Ratenlimit, Kill-Switch, Audit-Log. **Default: leer** |

Massenversand ist architektonisch ausgeschlossen: Executor akzeptiert nur Einzel-Actions mit Freigabe und hat Tages-Limits.

## 10. Sicherheits- & Datenschutzkonzept

**Secrets:** nur über Umgebungsvariablen / OS-Keychain / Secret-Manager; `.env.example` mit Platzhaltern; `.env` gitignored. Empfehlung: `gitleaks`/Pre-commit + GitHub Secret Scanning aktivieren. Keine Tokens in Logs/Fehlermeldungen.

**Datenklassifikation:**
| Klasse | Beispiele | Umgang |
|---|---|---|
| Öffentlich, sachlich | Praxisname, Adresse, Fachrichtung, Event | speicherbar, Quelle nötig |
| Personenbezogen (DSGVO) | Arztname, individuelle Mail/Telefon, LinkedIn-URL, Notizen zu Personen | Zweckbindung, Minimierung, Löschfristen, Rechtsgrundlage dokumentieren (Art. 6 (1) f, ggf. UWG/§7 für E-Mail-Werbung!) |
| Intern/vertraulich | Kundenlisten, Umsatz, Pipeline, doctolib-interne Infos | nur lokal/verschlüsselt, nie in Logs, nie in Git, nicht an externe Dienste ohne Freigabe |

**Architekturmaßnahmen:**
- PII-Redaction im Logger (Allowlist-Logging statt Blocklist), Logs ohne Namen/Mailadressen.
- Vor LLM-Aufrufen: Datenminimierung (nur benötigte Fakten, keine Kundenlisten, keine internen Umsatzdaten); Prüfung, ob doctolib-Richtlinie externe LLM-Nutzung mit Kundendaten erlaubt.
- Retention-Job (Rohcache, verwaiste Contacts), Lösch-/Auskunftsfunktion je Person.
- Verschlüsselte Platte/Datei (SQLCipher oder OS-Volume-Verschlüsselung).
- Audit-Log append-only für alle L3/L4-Aktionen.
- **Cold-E-Mail an Ärzte/Praxen (B2B):** in Deutschland UWG §7 – ohne Einwilligung meist unzulässig; Rechtslage mit doctolib-Legal klären, bevor E-Mail-Versand überhaupt in Betracht kommt. Entwürfe sind unkritisch, Versand nicht.
- Sessions in dieser Cloud-Umgebung sind ephemer und laufen über Dritt-Infrastruktur: **keine echten Kundendaten in dieses Repo/diese Session**, bis Datenhaltung geklärt ist (Details §13).

## 11. Entwicklungsphasen

| Phase | Inhalt | Echte Daten? |
|---|---|---|
| **0 – Fundament** | Repo-Setup, Domain-Modelle, Storage, Migrationen, Logging/Secrets, Tests, Policy-Config | nein (synthetische Testdaten) |
| **1 – Territory & Wissen** | Import (CSV) eigener Bestandskunden/Praxislisten, manuelle Erfassung, Netzwerkgraph (Hausarzt→Fach-Regeln), Scoring, „Heute: Saarbrücken“-Arbeitsliste | **ja, lokal**, sofort nutzbar |
| **2 – Research & Copilot** | Web-Research (Praxis-Websites), Fact/Source, Staleness; LLM: Praxisprofil, Meeting-Briefing, Einwand-Coach, Mail-/LinkedIn-Entwürfe (nur Text) | ja |
| **3 – Daily & Events** | Follow-ups, Tagesplan, Event-Radar, Gmail-Drafts (nur Entwurf), Kalender read-only | ja |
| **4 – Approval & Execution** | Freigabe-Workflow, kontrollierter Versand, Policy-gesteuerte L4 | nur nach Klärung §13 |
| **5 – Integration** | CRM-Sync, doctolib-Arztsuche (falls freigegeben), Web-UI | nach Freigabe |

**Früh mit echten Daten machbar:** CSV-Import, manuelle Erfassung, Praxis-Website-Recherche, Scoring/Arbeitslisten, Briefings/Coach (mit Datenminimierung), Event-Recherche.
**Später:** Mailversand, LinkedIn-Automatisierung, CRM-Schreibzugriff, doctolib-Arztsuche-Abruf.

**Scoring (nachvollziehbar, konfigurierbar):** Fachrichtung-Fit, Praxisgröße (Anzahl Ärzte), Referral-Nähe zu Bestandskunde, fehlende Online-Terminbuchung (belegt), Entfernung/Route, Event-Bezug, Datenfrische. Jede Punktzahl speichert `score_reasons[]`.

## 12. Technische Risiken

| Risiko | Gegenmaßnahme |
|---|---|
| Halluzinationen im Briefing | Fakt-ID-Pflicht, Validator, „Unbekannt“-Sektion |
| Veraltete Webdaten | `stale_after`, Anzeige des Alters, Re-Research-Vorschläge |
| ToS-/Rechtsverstoß beim Scraping | Policy-Gate, Allowlist, Freigabe je Quelle |
| Personenbezug / DSGVO | Klassifikation, Minimierung, Retention, Rechtsgrundlagen |
| Entity-Resolution (gleiche Praxis, mehrere Schreibweisen/Standorte, Gemeinschaftspraxen/MVZ) | `canonical_key`, manuelle Merge-Queue |
| Ableitungen (Hausarzt→Fach) als „Fakt“ missverstanden | `origin=derived` sichtbar kennzeichnen |
| Cloud-Session/LLM sieht Kundendaten | Datenminimierung, Freigabeklärung |
| Scope-Creep | Phasen mit Abnahme |
| Wartung von Extraktoren (Seitenlayouts) | deterministische Basis + Tests mit gespeicherten Fixtures |

## 13. Offene Fragen an dich (Entscheidungen vor Phase 0/1)

1. **Datenschutz/Compliance doctolib:** Darf ich mit Kundendaten (Bestandskunden, Pipeline) mit externen LLMs (Anthropic API) arbeiten? Gibt es eine interne AI-/Tool-Richtlinie? *Bis geklärt: Phase 1–2 nur mit öffentlichen Daten bzw. anonymisierten/synthetischen Testdaten.*
2. **Wo läuft es?** Lokal auf deinem Rechner (empfohlen für echte Daten) oder in dieser Cloud-Umgebung? Bei Cloud sollten keine Kundendaten ins Repo.
3. **doctolib-Arztsuche:** Hast du eine interne Freigabe/Datenquelle (Export, Territory-Listen, Salesforce-Report), die legitim nutzbar ist? Ohne sie: nur manuelle Einzelprüfung.
4. **CRM:** Nutzt ihr Salesforce o. ä.? Welche Exporte darfst du nutzen?
5. **E-Mail:** Firmen-Mail (Outlook/Gmail)? Ist Draft-Erstellung per API erlaubt? Rechtsabklärung Cold-Outreach (UWG §7).
6. **LinkedIn:** Sales Navigator vorhanden? Zunächst manuelles Einfügen von Profildaten?
7. **Sprache/Ton:** Deutsch (Sie-Form), Playbooks/Produktinfos/Einwandkatalog von doctolib – hast du interne Enablement-Materialien, die du einspeisen darfst?
8. **Produktportfolio:** Welche Produkte/Use-Cases sollen im Matching abgebildet werden?
9. **Stack:** Passt Python + CLI zuerst (Web-UI später), oder lieber TypeScript/Web von Anfang an?
10. **Geo:** Entfernungsberechnung offline (Haversine) ausreichend oder Routing gewünscht?

## 14. Empfehlung für den Start

Nach deiner Freigabe: **Phase 0 + Phase 1** mit synthetischen Daten für Tests. Erste echte Daten über deine legitimen Quellen (Import) lokal. Web-Research (Phase 2) startet mit Praxis-Websites, nicht mit der doctolib-Arztsuche.
