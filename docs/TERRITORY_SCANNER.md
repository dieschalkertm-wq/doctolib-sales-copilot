# Territory Scanner

Der Scanner ist eine **persönliche Automatisierungsschicht über dem bestehenden Workflow**, kein zweites CRM und kein
Nachbau interner Tools. Er übernimmt die manuelle Recherchekette „Gebiet → Praxen → Fachrichtung → Umgebung → bekannte
Daten → Research → Arbeitsliste“ und liefert eine nachvollziehbare, deterministische Arbeitsliste.
Grundlage bleibt [`ARCHITECTURE.md`](ARCHITECTURE.md); dieses Dokument beschreibt nur, was der Scanner darauf aufsetzt.

## Kette und Bausteine

```
„Bearbeite Saarbrücken“ (--radius, --specialty, --around-customers, --from-file …)
 │
 ├─ LocationResolver      scanner/area.py         Gebiet → Area (Ort | Region | Radius | Praxis-Umkreis | Kunden-Umfeld)
 ├─ SourceProvider(s)     scanner/providers/      Kandidaten aus EINER Quelle je Provider (austauschbar)
 ├─ ExistingDataMatcher   scanner/matcher.py      Kandidat ↔ Bestand: EXACT | POSSIBLE | NONE (konservativ)
 ├─ CandidateIngestor     scanner/ingest.py       EXACT → anhängen (nur Lücken) · POSSIBLE → Merge-Queue · NONE → neu
 ├─ NetworkAnalyzer       scanner/network.py      mögliche Überweiserbezüge zu Kundenpraxen (immer derived)
 ├─ Worklist-Bewertung    pipeline/worklist.py    deterministisches Scoring mit Begründung je Punkt
 ├─ ResearchEngine        scanner/research.py     optional: Website-Research, begrenzt, nur freigegebene Domains
 └─ ProspectListBuilder   scanner/builder.py      Arbeitslistenzeilen → ScanResult (Text via render.py, JSON via to_dict())
                          scanner/scanner.py      TerritoryScanner: orchestriert alles in EINER Transaktion
```

Alle Schreibvorgänge eines Scans laufen in einer Transaktion. `--dry-run` rollt am Ende zurück und führt keinen einzigen
Abruf aus (Vorschau ohne Nebenwirkung). Level 1/2: keine Mails, keine LinkedIn-Nachrichten, keine CRM-Änderungen.

## Provider: was funktioniert, was ist vorbereitet

Zwei Rollen (Anpassung an die bestehende Architektur):
* **SourceProvider** findet Praxen („Wer gibt es im Gebiet?“) – `scanner/providers/`.
* **ResearchProvider** reichert bekannte Praxen mit belegten Facts an – `research/`.

| Provider | Rolle | Status | Inhalt |
|---|---|---|---|
| `local_import` | Source | **funktioniert** | eigene Listen/Exporte (CSV/TSV) via `--from-file`; kein externer Abruf |
| `practice_website` | Research | **funktioniert** | Website-Signale mit robots.txt, Rate-Limit, Domain-Freigabe (Standard: alles gesperrt) |
| `map` | Source/Geocoder | **vorbereitet** | Interface + `Geocoder`-Protokoll; keine Implementierung, keine Datenquelle festgelegt |
| `doctolib` | Source | **vorbereitet** | Interface, Freigabe-Checkliste, Provenance-Pfad; keine Zugriffsmethode |
| `llm_gateway` | LLM | **vorbereitet** | Gateway mit Policy/Grounding; standardmäßig aus, kein Anbieter angebunden |

`copilot providers` zeigt den Ist-Zustand.

### Doctolib – Freigabe statt Verbot

Es gibt kein Architekturverbot. Ein Abruf ist erst möglich, wenn **alles** erfüllt ist:
1. `providers.doctolib.enabled: true`
2. vollständige Checkliste in `config/policies.yaml` (`tos_reviewed`, `robots_checked`, `rate_limit_agreed`,
   `internal_policy_ok`, `approved_by`)
3. eine konkrete `DoctolibAccessMethod` ist angebunden – die technische Zugriffsmethode (offizielle Schnittstelle, Export,
   kontrollierter Abruf) wird **separat** entschieden
4. die Domain steht zusätzlich in `research.allowed_domains`

Bis dahin liefert `--provider doctolib` einen klaren Fehler mit den fehlenden Punkten. Alle anderen Provider erreichen
`doctolib.*` nie (auch nicht über Weiterleitungen einer Praxis-Website): `FetchPolicy(allow_doctolib=False)`; nur
`DoctolibProvider.fetch_policy()` schaltet das frei, und auch nur bei vollständiger Freigabe. Nicht vorgesehen und
nicht zulässig: Umgehung von Schutzmechanismen, Login-Automatisierung, CAPTCHA-Umgehung, aggressives Massenabrufen.
LinkedIn bleibt immer gesperrt (nur manuelle Eingabe/offizielle APIs). Google Maps wird nicht gescrapt.

Belegte Doctolib-Signale entstehen als Fact mit Quelle: `doctolib_link_present` (Link auf der Praxis-Website) oder
`doctolib_profile_public` (Profil, aus dem Provider). Ohne Beleg steht in der Liste „unbekannt (nicht belegt)“.

## Genauigkeit von Ort und Entfernung

* Praxen ohne exakte Koordinaten liegen am **Ortsmittelpunkt** (`geo_precision=place`) mit Unsicherheit
  **±5 km** (Annahme, `config/territory.yaml` → `geo.place_uncertainty_km`, je Ort überschreibbar).
* Exakte Koordinaten (Import-Spalten `lat`/`lon`, später ein Geocoder, `KnowledgeService.set_exact_location`) haben
  Unsicherheit 0. Die Präzision darf nur steigen, nie sinken.
* Das Suchzentrum „um Saarbrücken“ ist per Definition der Ortsmittelpunkt (Unsicherheit 0); „um Praxis X“ erbt deren
  Unsicherheit.
* Radiusprüfungen sind **dreiwertig**: `inside` (auch im ungünstigsten Fall drinnen), `possible` (je nach echtem
  Standort), `outside`. Unsicherheiten addieren sich (Worst Case). `--strict-radius` blendet `possible` aus.
* Ausgaben zeigen Näherungen als Näherungen: `≈12 km (±5 km) · möglicherweise im Radius`; exakte Werte ohne „≈“.
  Abgeleitete Beziehungen speichern die Unsicherheit an der Beziehung (`distance_uncertainty_km`).
* Praxen ohne Geodaten werden bei Radiussuchen nie „geraten“, sondern gezählt und gemeldet.
* „Bearbeite Saarbrücken“ ohne Radius ordnet nach **Ortsangabe** zu, nicht nach Geodaten.

## Abgleich mit vorhandenen Daten (ExistingDataMatcher)

Ein Scan erzeugt nie blind neue Datensätze. Ergebnis je Kandidat:

| Ergebnis | Regel (höchste Confidence gewinnt) | Aktion |
|---|---|---|
| **EXACT** | gleicher Schlüssel (Name+PLZ+Straße normalisiert) 1,00 · gleiche Website **und** gleiche Straße 0,97 · frühere Nutzerentscheidung „gleich“ | an bestehende Praxis anhängen, **nur Lücken füllen**, Herkunft ergänzen |
| **POSSIBLE** | gleicher Name+PLZ 0,80 · gleiche Adresse (PLZ+Straße) 0,75 · ähnlicher Name+PLZ 0,65 · gleiche Website 0,65 · gleicher Name+Ort 0,60 · gleicher Arzt+Ort 0,55 · ähnlicher Name+Ort 0,50 · mehrdeutiges EXACT | **Merge-Queue**, nichts wird zusammengeführt |
| **NONE** | sonst | neue Praxis (+ Herkunft) |

Reine Namensähnlichkeit führt **nie** zu EXACT. Bereits als „verschieden“ entschiedene Paare tauchen nicht erneut auf.
Bereits importierte Status (Kunde / Prospect / kontaktiert) bleiben unangetastet und erscheinen in der Liste
(`--unworked` blendet kontaktierte/laufende aus; Kunden werden immer ausgewiesen ausgeschlossen).

Merge-Queue: `copilot merge list` · `copilot merge resolve ID --same|--different`. `--same` hängt an die Praxis an
(nur Lücken füllen) und merkt sich die Zuordnung; `--different` legt den Kandidaten als eigene Praxis an.

## Überweisernetzwerk

Der Scanner leitet Bezüge Kundenpraxis → gefundene Fachpraxis ausschließlich als **`derived`** ab (Regeln aus
`config/referral_rules.yaml`, Reichweite `scanner.network_radius_km` bzw. der Scan-Radius). Sie erscheinen als
„ABGELEITET (Regel …) – nicht belegt“ und fließen mit dem niedrigsten Gewicht in den Score ein. `observed` entsteht nur
über einen aktiven Fact (`copilot network observe`); die Datenbank-Constraints (observed braucht `fact_id`, derived braucht
`rule_id`) werden nicht umgangen.

## Research aus dem Scan

`--research` führt Website-Research für Treffer aus, aber: Obergrenze `--research-limit` **und** Konfig-Obergrenze
`scanner.research_max_practices`; nicht freigegebene Domains werden **vor** jedem Netzwerkzugriff übersprungen (kein
Research-Eintrag); robots.txt und Rate-Limit gelten wie beim Einzelabruf; im Dry-Run findet nichts statt. Neue Facts
fließen sofort in die Bewertung zurück (z. B. belegter Doctolib-Link → als „bereits doctolib“ ausgeschlossen).

## Arbeitsliste (Output)

Je Praxis: Name · Fachrichtung · Ort/Adresse · Entfernung (mit Unsicherheit) · Quelle (Herkunft) · Status
(Kunde/Prospect/Stufe/unbekannt) · Research-Status · Doctolib-Signal (nur belegt) · Website · Ärzte · relevante Facts ·
Netzwerkbezug · Score mit Begründung · „Unbekannt / zu klären“ · nächste Aktion. Ausgeschlossene Praxen stehen mit Grund
in der Liste („Ausgeschlossen“) – nichts verschwindet still. Dieselben Daten liefert `--json` für eine spätere Web-UI.
Sortierung: Score ↓, Entfernung ↑, Name, ID (deterministisch, kein KI-Scoring).

## LLM-Gateway (vorbereitet)

`llm/context.py` baut je Aufgabe einen **typisierten Kontext einer Praxis**: aktuelle, belegte Facts mit ID und Quelle;
Praxisname/Ärztenamen/Kontaktdaten nur bei ausdrücklicher Policy; nie Pipeline-Status, Notizen, Netzwerk, andere Praxen
oder Kundenlisten. `llm/gateway.py` erzwingt: `llm.enabled`, externe Anbieter nur mit `llm.allow_external`, PII-Prüfung von
Kontext und Nutzereingabe, valides JSON im `GroundedOutput`-Schema und **Fact-Referenzierung**: Aussagen vom Typ `fact`
brauchen gültige Fact-IDs aus dem Kontext und dürfen keine URLs/Mails/Telefonnummern enthalten, die nicht in den
zitierten Facts stehen; alles andere ist `hypothesis` (als „ANNAHME (nicht belegt)“ ausgegeben) oder `question`.
Audit nur mit Metadaten. Es ist **kein** Anbieter angebunden und Standard ist „aus“.
Praxisprofil, Meeting-Briefing, Einwand-Coach und Entwürfe (Phase 2) setzen auf diese Schicht auf.

## Additive Erweiterungen gegenüber ARCHITECTURE.md

Keine bestehende Regel wurde geändert oder umgangen. Neu (alles additiv):

| Änderung | Begründung |
|---|---|
| Tabelle `k_practice_origin` (Migration 0006) | Spalte „Quelle“ der Arbeitsliste: Provenienz der *Existenz* einer Praxis, getrennt von zeitabhängigen Facts (R-Schicht bleibt unangetastet) |
| Tabelle `k_merge_candidate` (0006) | die in ARCHITECTURE §12 vorgesehene manuelle Merge-Queue |
| Spalte `k_network_relationship.distance_uncertainty_km` (0006) | keine falsche Präzision bei abgeleiteten Distanzen |
| Pakete `scanner/` und `llm/` | `llm/` steht in §4; `scanner/` bündelt die Territory-Kette (Pipeline-Schicht + Connectors) |
| Doctolib-Sperre von „fest im Code“ zu „Freigabe-Checkliste + Provider“ | Präzisierung des Nutzers: kein Architekturverbot; §7 verlangt Klärung *vor* dem produktiven Einsatz, was die Checkliste erzwingt |
| Abschnitte `providers`, `scanner`, `llm` in `config/policies.yaml` | Konfiguration/Freigaben ohne Secrets |
| `lat`/`lon` im Import (`PracticeRecord`) | exakte Koordinaten aus der Quelle, wenn vorhanden |

## Offene technische Entscheidungen

1. **Geodatenquelle/Geocoder** (offene Daten? lizenzierte API? interner Export?) – bestimmt, wann Entfernungen exakt werden.
2. **doctolib-Zugriffsmethode** (interner Export/Schnittstelle vs. öffentlicher Abruf) und die Freigabe-Checkliste.
3. **Reale Werte**: Ortsunsicherheit (5 km ist eine Annahme), Scoring-Gewichte, Überweiser-Regeln, Confidence-Schwellen.
4. **Merge-Queue-Bedienung**: aktuell CLI; für viele Einträge wäre eine Liste mit Gegenüberstellung in der UI sinnvoll.
5. **Herkunft bestehender Praxen**: vor Migration 0006 importierte Praxen haben keinen Herkunftsnachweis (Ausgabe: „unbekannt“).
6. **LLM-Anbieter** und die interne KI-/Datenrichtlinie (Voraussetzung, bevor `llm.enabled` sinnvoll ist).
