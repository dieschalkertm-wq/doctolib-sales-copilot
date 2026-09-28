"""Audit-Log-Grundlage. Allowlist-Logging: nur unkritische Schlüssel und Kurzwerte, keine Namen/Adressen/Mails."""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from copilot.domain.timeutil import to_iso, utcnow
from copilot.errors import ValidationFailed

ALLOWED_DETAIL_KEYS = frozenset({
    "rows", "created", "updated", "unchanged", "failed", "warnings", "role", "dry_run", "file_sha256",
    "provider", "status", "error_code", "source_id", "research_id", "fact_count", "fact_id", "rule_id",
    "origin", "rel_type", "count", "radius_km", "skipped_no_geo", "level", "scope", "version",
})
_SAFE_STRING = re.compile(r"^[A-Za-z0-9_.:>\-/ ]{0,80}$")


def _sanitize(details: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in details.items():
        if key not in ALLOWED_DETAIL_KEYS:
            raise ValidationFailed(f"Audit-Detail '{key}' nicht erlaubt (Allowlist)", code="audit_key_not_allowed")
        if isinstance(value, str) and (not _SAFE_STRING.match(value) or "@" in value):
            raise ValidationFailed(f"Audit-Detail '{key}': Wert nicht erlaubt", code="audit_value_not_allowed")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise ValidationFailed(f"Audit-Detail '{key}': nur Skalare erlaubt", code="audit_value_not_allowed")
        clean[key] = value
    return clean


class AuditLog:
    def __init__(self, conn: sqlite3.Connection, actor: str):
        self.conn, self.actor = conn, actor

    def record(
        self,
        event_type: str,
        summary: str,
        *,
        entity_type: str | None = None,
        entity_id: int | None = None,
        content_hash: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO a_audit_event (occurred_at, actor, event_type, entity_type, entity_id, summary, content_hash, details)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (to_iso(utcnow()), self.actor, event_type, entity_type, entity_id, summary, content_hash,
             json.dumps(_sanitize(details or {}), sort_keys=True)),
        )
        return int(cur.lastrowid)

    def tail(self, limit: int = 20) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM a_audit_event ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
