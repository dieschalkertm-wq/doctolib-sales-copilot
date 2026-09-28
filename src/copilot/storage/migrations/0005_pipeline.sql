-- P: Pipeline/Vertrieb. Getrennt von Knowledge und Research.
CREATE TABLE p_customer (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id INTEGER NOT NULL UNIQUE REFERENCES k_practice (id),
    since       TEXT,
    products    TEXT NOT NULL DEFAULT '[]',
    notes       TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE p_prospect (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    practice_id   INTEGER NOT NULL UNIQUE REFERENCES k_practice (id),
    stage         TEXT NOT NULL DEFAULT 'identified' CHECK (stage IN
                    ('identified','researched','contacted','meeting','proposal','won','lost','parked')),
    score         REAL,
    score_reasons TEXT NOT NULL DEFAULT '[]',
    scored_at     TEXT,
    notes         TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
-- Eine Kundenpraxis wird kein (neuer) Prospect; der Übergang Prospect -> Kunde ist erlaubt.
CREATE TRIGGER p_prospect_not_customer BEFORE INSERT ON p_prospect
WHEN EXISTS (SELECT 1 FROM p_customer WHERE practice_id = NEW.practice_id)
BEGIN SELECT RAISE(ABORT, 'practice is already a customer'); END;
