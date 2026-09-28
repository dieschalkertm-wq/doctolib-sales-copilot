"""SQLite-Zugriff: Verbindung, Transaktionen (mit Savepoints) und versionierte SQL-Migrationen."""

from __future__ import annotations

import hashlib
import itertools
import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import resources
from pathlib import Path

from copilot.domain.timeutil import to_iso, utcnow
from copilot.errors import ConfigError

_savepoints = itertools.count(1)


def connect(db_path: Path | str) -> sqlite3.Connection:
    is_memory = str(db_path) == ":memory:"
    if not is_memory:
        path = Path(db_path)
        created = not path.parent.exists()
        path.parent.mkdir(parents=True, exist_ok=True)
        if created:  # Rechte nur für Ordner, die wir selbst angelegt haben – nie für bestehende (z. B. ~)
            os.chmod(path.parent, 0o700)
    conn = sqlite3.connect(str(db_path), isolation_level=None)  # Transaktionen explizit
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if not is_memory:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(str(db_path) + suffix)
            if candidate.exists():
                os.chmod(candidate, 0o600)
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Äußere Transaktion oder Savepoint, wenn bereits eine läuft (z. B. Dry-Run-Import)."""
    if conn.in_transaction:
        name = f"sp_{next(_savepoints)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
    else:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        conn.execute("COMMIT")


def _migrations() -> list[tuple[str, str]]:
    folder = resources.files("copilot.storage") / "migrations"
    items = sorted((p for p in folder.iterdir() if p.name.endswith(".sql")), key=lambda p: p.name)
    return [(p.name.removesuffix(".sql"), p.read_text(encoding="utf-8")) for p in items]


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Wendet ausstehende Migrationen an. Bereits angewendete werden gegen ihre Prüfsumme verifiziert."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT version, checksum FROM schema_migrations")}
    newly: list[str] = []
    for version, sql in _migrations():
        checksum = _checksum(sql)
        if version in applied:
            if applied[version] != checksum:
                raise ConfigError(f"Migration {version} wurde nach dem Anwenden verändert", code="migration_tampered")
            continue
        try:
            conn.executescript(
                f"BEGIN;\n{sql}\n"
                f"INSERT INTO schema_migrations VALUES ('{version}', '{checksum}', '{to_iso(utcnow())}');\nCOMMIT;"
            )
        except sqlite3.Error as exc:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise ConfigError(f"Migration {version} fehlgeschlagen: {exc}", code="migration_failed") from exc
        newly.append(version)
    return newly


def schema_version(conn: sqlite3.Connection) -> str | None:
    try:
        row = conn.execute("SELECT max(version) AS v FROM schema_migrations").fetchone()
    except sqlite3.OperationalError:
        return None
    return row["v"]
