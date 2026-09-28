-- K: Knowledge – dauerhaft gültige Stammdaten. KEINE Rechercheergebnisse (die leben als r_fact).
CREATE TABLE k_specialty (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    code      TEXT NOT NULL UNIQUE,
    name      TEXT NOT NULL,
    parent_id INTEGER REFERENCES k_specialty (id)
);

CREATE TABLE k_practice (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    street        TEXT,
    plz           TEXT CHECK (plz IS NULL OR (length(plz) = 5 AND plz NOT GLOB '*[^0-9]*')),
    ort           TEXT,
    ort_key       TEXT,
    region        TEXT,
    lat           REAL CHECK (lat IS NULL OR lat BETWEEN -90 AND 90),
    lon           REAL CHECK (lon IS NULL OR lon BETWEEN -180 AND 180),
    geo_precision TEXT CHECK (geo_precision IS NULL OR geo_precision IN ('exact', 'place')),
    website_url   TEXT,
    canonical_key TEXT NOT NULL UNIQUE,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    CHECK ((lat IS NULL) = (lon IS NULL))
);
CREATE INDEX k_practice_ort_idx ON k_practice (ort_key);
CREATE INDEX k_practice_region_idx ON k_practice (region);

CREATE TABLE k_doctor (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name     TEXT NOT NULL,
    title         TEXT,
    canonical_key TEXT NOT NULL
);

CREATE TABLE k_practice_doctor (
    practice_id INTEGER NOT NULL REFERENCES k_practice (id) ON DELETE CASCADE,
    doctor_id   INTEGER NOT NULL REFERENCES k_doctor (id) ON DELETE CASCADE,
    PRIMARY KEY (practice_id, doctor_id)
);

CREATE TABLE k_practice_specialty (
    practice_id  INTEGER NOT NULL REFERENCES k_practice (id) ON DELETE CASCADE,
    specialty_id INTEGER NOT NULL REFERENCES k_specialty (id),
    PRIMARY KEY (practice_id, specialty_id)
);

CREATE TABLE k_doctor_specialty (
    doctor_id    INTEGER NOT NULL REFERENCES k_doctor (id) ON DELETE CASCADE,
    specialty_id INTEGER NOT NULL REFERENCES k_specialty (id),
    PRIMARY KEY (doctor_id, specialty_id)
);
