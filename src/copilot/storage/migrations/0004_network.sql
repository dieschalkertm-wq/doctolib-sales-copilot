-- K: Überweisernetzwerk. 'observed' verlangt einen Fact (Beleg); 'derived' verlangt eine Regel-ID.
CREATE TABLE k_network_relationship (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    from_type   TEXT NOT NULL CHECK (from_type IN ('practice','doctor','specialty')),
    from_id     INTEGER NOT NULL,
    to_type     TEXT NOT NULL CHECK (to_type IN ('practice','doctor','specialty')),
    to_id       INTEGER NOT NULL,
    rel_type    TEXT NOT NULL CHECK (rel_type IN ('refers_to','same_practice','shared_location','colleague')),
    origin      TEXT NOT NULL CHECK (origin IN ('derived','observed','manual')),
    strength    REAL CHECK (strength IS NULL OR strength BETWEEN 0 AND 1),
    distance_km REAL CHECK (distance_km IS NULL OR distance_km >= 0),
    fact_id     INTEGER REFERENCES r_fact (id),
    rule_id     TEXT,
    note        TEXT,
    created_at  TEXT NOT NULL,
    CHECK (origin <> 'observed' OR fact_id IS NOT NULL),
    CHECK (origin = 'observed' OR fact_id IS NULL),
    CHECK (origin <> 'derived' OR rule_id IS NOT NULL),
    CHECK (NOT (from_type = to_type AND from_id = to_id)),
    UNIQUE (from_type, from_id, to_type, to_id, rel_type, origin)
);
CREATE INDEX k_network_from_idx ON k_network_relationship (from_type, from_id);
CREATE INDEX k_network_to_idx ON k_network_relationship (to_type, to_id);
