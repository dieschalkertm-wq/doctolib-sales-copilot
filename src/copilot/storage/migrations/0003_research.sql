-- R: Research – zeitabhängig, append-only, immer mit Quelle und Zeitstempel.
CREATE TABLE r_source (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type   TEXT NOT NULL CHECK (source_type IN
                    ('practice_website','doctolib_public','event_page','registry','manual','linkedin_manual')),
    url           TEXT,
    publisher     TEXT,
    retrieved_at  TEXT NOT NULL,
    published_at  TEXT,
    content_hash  TEXT,
    robots_status TEXT NOT NULL CHECK (robots_status IN ('allowed','not_applicable')),
    tos_ref       TEXT,
    reliability   INTEGER NOT NULL CHECK (reliability BETWEEN 1 AND 5),
    raw_ref       TEXT,
    CHECK (source_type = 'manual' OR url IS NOT NULL)
);
CREATE TRIGGER r_source_immutable BEFORE UPDATE OF
    source_type, url, retrieved_at, content_hash, robots_status ON r_source
BEGIN SELECT RAISE(ABORT, 'source provenance is immutable'); END;

CREATE TABLE r_research (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id   INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    provider     TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('started','succeeded','failed','blocked')),
    started_at   TEXT NOT NULL,
    finished_at  TEXT,
    error_code   TEXT
);
CREATE INDEX r_research_subject_idx ON r_research (subject_type, subject_id);

CREATE TABLE r_fact (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type  TEXT NOT NULL CHECK (subject_type IN ('practice','doctor','specialty','event')),
    subject_id    INTEGER NOT NULL,
    key           TEXT NOT NULL,
    value         TEXT NOT NULL,              -- JSON
    source_id     INTEGER NOT NULL REFERENCES r_source (id),   -- ohne Quelle kein Fact
    research_id   INTEGER REFERENCES r_research (id),
    confidence    REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    evidence      TEXT,
    observed_at   TEXT NOT NULL,
    stale_after   TEXT,
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded','retracted')),
    superseded_by INTEGER REFERENCES r_fact (id),
    CHECK (stale_after IS NULL OR stale_after >= observed_at)
);
CREATE INDEX r_fact_subject_idx ON r_fact (subject_type, subject_id, key, status);
-- Claims sind unveränderlich; nur status/superseded_by dürfen sich ändern.
CREATE TRIGGER r_fact_immutable BEFORE UPDATE OF
    subject_type, subject_id, key, value, source_id, research_id, confidence, evidence, observed_at, stale_after
    ON r_fact
BEGIN SELECT RAISE(ABORT, 'fact claims are immutable; supersede instead'); END;

CREATE TABLE r_event (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    name                  TEXT NOT NULL,
    date_from             TEXT NOT NULL,
    date_to               TEXT,
    ort                   TEXT,
    lat                   REAL,
    lon                   REAL,
    url                   TEXT,
    registration_deadline TEXT,
    distance_km           REAL CHECK (distance_km IS NULL OR distance_km >= 0),
    source_id             INTEGER NOT NULL REFERENCES r_source (id)
);
CREATE TABLE r_event_specialty (
    event_id     INTEGER NOT NULL REFERENCES r_event (id) ON DELETE CASCADE,
    specialty_id INTEGER NOT NULL REFERENCES k_specialty (id),
    PRIMARY KEY (event_id, specialty_id)
);
