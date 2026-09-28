-- A: Audit-Log (append-only). Enthält bewusst keine Klartext-PII (siehe AuditLog-Allowlist).
CREATE TABLE a_audit_event (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at  TEXT NOT NULL,
    actor        TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    entity_type  TEXT,
    entity_id    INTEGER,
    summary      TEXT NOT NULL,
    content_hash TEXT,
    details      TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX a_audit_event_type_idx ON a_audit_event (event_type, occurred_at);
CREATE TRIGGER a_audit_event_no_update BEFORE UPDATE ON a_audit_event
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
CREATE TRIGGER a_audit_event_no_delete BEFORE DELETE ON a_audit_event
BEGIN SELECT RAISE(ABORT, 'audit log is append-only'); END;
