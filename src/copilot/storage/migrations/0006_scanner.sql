-- Territory Scanner (additiv): Herkunft von Praxen, Merge-Queue, ehrliche Distanz-Unsicherheit.

-- K: Wer hat mir gesagt, dass es diese Praxis gibt? (Provenienz der Existenz; KEINE zeitabhängigen Fakten)
CREATE TABLE k_practice_origin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id   INTEGER NOT NULL REFERENCES k_practice (id) ON DELETE CASCADE,
    provider      TEXT NOT NULL,       -- z. B. local_import, doctolib, map
    source_ref    TEXT NOT NULL,       -- z. B. file:<sha256-Präfix>; nie Klartext-PII
    first_seen_at TEXT NOT NULL,
    last_seen_at  TEXT NOT NULL,
    UNIQUE (practice_id, provider, source_ref)
);

-- K: Merge-Queue. Mögliche Dubletten werden NIE automatisch zusammengeführt, sondern hier zur Prüfung abgelegt.
CREATE TABLE k_merge_candidate (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id   INTEGER NOT NULL REFERENCES k_practice (id) ON DELETE CASCADE,
    candidate_key TEXT NOT NULL,
    provider      TEXT NOT NULL,
    source_ref    TEXT NOT NULL,
    payload       TEXT NOT NULL,       -- JSON des Kandidaten (lokal, personenbezogen, nie in Logs/Audit)
    confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    reasons       TEXT NOT NULL,       -- JSON-Liste maschinenlesbarer Gründe
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'same', 'different')),
    created_at    TEXT NOT NULL,
    resolved_at   TEXT,
    UNIQUE (practice_id, candidate_key, provider)
);
CREATE INDEX k_merge_candidate_status_idx ON k_merge_candidate (status);
CREATE INDEX k_merge_candidate_key_idx ON k_merge_candidate (candidate_key, provider);

-- Abgeleitete Beziehungen kennen ihre Distanz nur näherungsweise (Ortsmittelpunkte).
ALTER TABLE k_network_relationship
    ADD COLUMN distance_uncertainty_km REAL CHECK (distance_uncertainty_km IS NULL OR distance_uncertainty_km >= 0);
