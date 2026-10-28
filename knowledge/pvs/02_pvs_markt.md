# Was ein PVS kann – und was die Praxen heute haben

> Allgemeines Marktwissen, Stand Oktober 2026. Hersteller und Produktnamen ändern sich durch Übernahmen.
> Aktuelle Verbreitung: Installationsstatistik der KBV (kbv.de → Praxis-IT). Bei Bedarf prüfe ich das nach.

## Die 3 wichtigsten Punkte
1. Ein PVS ist das **Betriebssystem der Praxis**: Patientenakte, Termine, Formulare, Abrechnung und TI.
2. Jedes Kassen-PVS muss von der **KBV zertifiziert** sein. Sonst darf die Praxis damit nicht abrechnen.
3. Praxen bleiben oft **10 Jahre und länger** beim selben PVS. Ein Wechsel braucht einen Grund:
   Ärger, Kosten, veraltete Technik, Praxisübernahme oder ein Ende der Unterstützung durch den Hersteller.

## Die Grundfunktionen jedes PVS (Checkliste)

| Bereich | Was es macht |
|---|---|
| Stammdaten | Patientendaten, Kartenlesen (eGK) |
| Karteikarte | Befunde, Diagnosen (ICD-10), Leistungen, Medikation |
| Termine | Kalender, Wartezimmer, Recall (Erinnerungen) |
| Formulare | Überweisung, Rezept, Krankmeldung, Heil- und Hilfsmittel, Blankodruck |
| Abrechnung | Kasse (EBM/KV), Privat (GOÄ), IGeL, DMP, HZV, Plausibilitätsprüfung |
| TI | E-Rezept, eAU, ePA, KIM, VSDM, Notfalldaten, Medikationsplan |
| Schnittstellen | Labor, Geräte, Online-Termine, Telefon |
| Statistik | Fallzahlen, Umsatz, Auswertungen |
| Benutzer | Rechte, mehrere Ärzte und Standorte |

## Wie die Systeme gebaut sind

| Typ | Einfach gesagt | Typische Sorgen |
|---|---|---|
| **Lokal installiert** (Server in der Praxis) | Klassisch. Läuft auf eigenem Server, Updates per IT-Betreuer. | Wartung, Backups, alte Hardware, Updates |
| **Cloud / Browser** | Läuft im Rechenzentrum, Zugang über Internet | „Sind meine Daten sicher?“, „Was ist, wenn das Internet ausfällt?“ |

**Für dich:** Bei Cloud-Lösungen kommen fast immer die Fragen **Datenschutz** und **Internetausfall**. Die Antworten dafür muss ich aus den Doctolib-Unterlagen holen → `produkt/`.

## Verbreitete Systeme (Auswahl, ohne Gewähr)

| Hersteller | Bekannte Produkte | Hinweis |
|---|---|---|
| **CompuGroup Medical (CGM)** | MEDISTAR, ALBIS, TURBOMED, CGM M1 PRO | Größter Anbieter, viele ältere Installationen |
| **medatixx** | medatixx, x.isynet, x.concept, x.comfort | Weit verbreitet, besonders bei Hausärzten |
| **Zollsoft** | tomedo | Beliebt bei Mac-Nutzern |
| **T2med** | T2med | Modernerer Anbieter |
| **Indamed** | MEDICAL OFFICE | |
| **Duria** | Duria | |
| **Psychotherapie** | z. B. psyprax, Elefant | Eigene Welt, eigenes Antragswesen |

Was jedes System genau kann, was es kostet und wo es Schwächen hat, sammeln wir zusammen. Dafür sind
deine Gespräche die beste Quelle. Ich lege zu jedem System eine Karte an, sobald du Infos hast.

## Typische Wechselhürden – und worauf du achtest

| Hürde | Frage, die du stellst |
|---|---|
| **Datenübernahme** | „Wie viele Jahre Patientendaten haben Sie im System?“ |
| **Vertrag / Kündigungsfrist** | „Wie lange läuft Ihr Vertrag noch? Wann ist die Kündigungsfrist?“ |
| **Zeitpunkt** | „Welcher Quartalsbeginn wäre für Sie realistisch?“ |
| **Schulung** | „Wie viele Mitarbeiter arbeiten im System?“ |
| **Geräte** | „Welche Geräte und welches Labor sind angebunden?“ |
| **Angst vor Ausfall** | „Was wäre für Sie das Schlimmste beim Wechsel?“ |

## Zahnarztpraxen – eigene Software-Welt

Zahnärzte rechnen über die **KZV** ab (BEMA für Kasse, GOZ für Privat). Sie nutzen deshalb eigene Programme.

| Hersteller | Produkt |
|---|---|
| Dampsoft | DS-Win |
| Computer konkret | ivoris |
| solutio | charly |
| CGM | CGM Z1 |
| evident | evident |

**VDDS** (Verband Deutscher Dental-Software) legt gemeinsame Schnittstellen für Zahnarzt-Software fest,
zum Beispiel für Röntgen und Bilddaten. Online-Termintools docken über solche Schnittstellen oder über eigene
Konnektoren an das Zahnarzt-Programm an.
