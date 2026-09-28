import sqlite3

import pytest

from copilot.storage.db import connect, migrate, schema_version, transaction
from copilot.errors import ConfigError, ValidationFailed


def test_migrate_is_idempotent_and_versioned():
    conn = connect(":memory:")
    first = migrate(conn)
    assert first and migrate(conn) == []
    assert schema_version(conn) == first[-1]


def test_tampered_migration_is_detected():
    conn = connect(":memory:")
    migrate(conn)
    conn.execute("UPDATE schema_migrations SET checksum = 'x' WHERE version = '0001_audit'")
    with pytest.raises(ConfigError) as exc:
        migrate(conn)
    assert exc.value.code == "migration_tampered"


def test_audit_log_is_append_only(app):
    eid = app.audit.record("test.event", "hello", details={"count": 1})
    with pytest.raises(sqlite3.IntegrityError):
        app.conn.execute("UPDATE a_audit_event SET summary = 'x' WHERE id = ?", (eid,))
    with pytest.raises(sqlite3.IntegrityError):
        app.conn.execute("DELETE FROM a_audit_event WHERE id = ?", (eid,))


def test_audit_allowlist_blocks_pii(app):
    with pytest.raises(ValidationFailed):
        app.audit.record("x", "y", details={"name": "Dr. Erika"})          # Schlüssel nicht erlaubt
    with pytest.raises(ValidationFailed):
        app.audit.record("x", "y", details={"role": "erika@example.com"})   # Wert nicht erlaubt
    with pytest.raises(ValidationFailed):
        app.audit.record("x", "y", details={"count": [1, 2]})


def test_transaction_rolls_back_and_nests(app):
    with pytest.raises(RuntimeError):
        with transaction(app.conn):
            app.audit.record("a", "b")
            raise RuntimeError
    assert app.audit.tail() == []
    with transaction(app.conn):
        with pytest.raises(RuntimeError):
            with transaction(app.conn):  # Savepoint
                app.audit.record("inner", "b")
                raise RuntimeError
        app.audit.record("outer", "b")
    assert [r["event_type"] for r in app.audit.tail()] == ["outer"]


def test_db_file_permissions(settings):
    import os
    from copilot.app import App
    App.open(settings).close()
    assert oct(os.stat(settings.db_path).st_mode & 0o777) == "0o600"
    assert oct(os.stat(settings.data_dir).st_mode & 0o777) == "0o700"


def test_existing_directories_keep_their_permissions(tmp_path):
    existing = tmp_path / "shared"
    existing.mkdir()
    existing.chmod(0o755)
    connect(existing / "x.sqlite3").close()
    import os
    assert oct(os.stat(existing).st_mode & 0o777) == "0o755"
