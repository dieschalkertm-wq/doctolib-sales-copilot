from __future__ import annotations

import sqlite3

from copilot.domain.enums import EntityType, RelationOrigin
from copilot.domain.models import NetworkRelationship
from copilot.domain.timeutil import from_iso, to_iso, utcnow


def _rel(row: sqlite3.Row) -> NetworkRelationship:
    d = dict(row)
    d["created_at"] = from_iso(d["created_at"])
    return NetworkRelationship.model_validate(d)


class NetworkRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, r: NetworkRelationship) -> tuple[NetworkRelationship, bool]:
        """Idempotent über UNIQUE(from,to,rel_type,origin). Gibt (Relation, neu_angelegt) zurück."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO k_network_relationship (from_type, from_id, to_type, to_id, rel_type, origin, strength,"
            " distance_km, fact_id, rule_id, note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (r.from_type.value, r.from_id, r.to_type.value, r.to_id, r.rel_type.value, r.origin.value, r.strength,
             r.distance_km, r.fact_id, r.rule_id, r.note, to_iso(utcnow())))
        created = cur.rowcount > 0
        row = self.conn.execute(
            "SELECT * FROM k_network_relationship WHERE from_type=? AND from_id=? AND to_type=? AND to_id=?"
            " AND rel_type=? AND origin=?",
            (r.from_type.value, r.from_id, r.to_type.value, r.to_id, r.rel_type.value, r.origin.value)).fetchone()
        return _rel(row), created

    def for_entity(self, entity_type: EntityType, entity_id: int, *, origin: RelationOrigin | None = None,
                   direction: str = "any") -> list[NetworkRelationship]:
        clauses = {"out": "(from_type=? AND from_id=?)", "in": "(to_type=? AND to_id=?)",
                   "any": "((from_type=? AND from_id=?) OR (to_type=? AND to_id=?))"}
        args: list = [entity_type.value, entity_id] * (2 if direction == "any" else 1)
        sql = f"SELECT * FROM k_network_relationship WHERE {clauses[direction]}"
        if origin:
            sql, args = sql + " AND origin=?", [*args, origin.value]
        return [_rel(r) for r in self.conn.execute(sql + " ORDER BY id", args)]
