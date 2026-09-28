from __future__ import annotations

import json
import sqlite3
from typing import Any

from copilot.domain.enums import ProspectStage
from copilot.domain.models import Customer, Prospect
from copilot.domain.timeutil import from_iso, to_iso, utcnow


def _prospect(row: sqlite3.Row) -> Prospect:
    d = dict(row)
    d["score_reasons"] = json.loads(d["score_reasons"])
    d["scored_at"] = from_iso(d["scored_at"]) if d["scored_at"] else None
    d.pop("created_at"), d.pop("updated_at")
    return Prospect.model_validate(d)


class PipelineRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def get_customer(self, practice_id: int) -> Customer | None:
        row = self.conn.execute("SELECT * FROM p_customer WHERE practice_id=?", (practice_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["products"] = json.loads(d["products"])
        d.pop("created_at")
        return Customer.model_validate(d)

    def insert_customer(self, c: Customer) -> Customer:
        cur = self.conn.execute(
            "INSERT INTO p_customer (practice_id, since, products, notes, created_at) VALUES (?,?,?,?,?)",
            (c.practice_id, c.since, json.dumps(c.products), c.notes, to_iso(utcnow())))
        return c.model_copy(update={"id": int(cur.lastrowid)})

    def customer_practice_ids(self) -> set[int]:
        return {r[0] for r in self.conn.execute("SELECT practice_id FROM p_customer")}

    def get_prospect(self, practice_id: int) -> Prospect | None:
        row = self.conn.execute("SELECT * FROM p_prospect WHERE practice_id=?", (practice_id,)).fetchone()
        return _prospect(row) if row else None

    def insert_prospect(self, practice_id: int, stage: ProspectStage = ProspectStage.IDENTIFIED) -> Prospect:
        now = to_iso(utcnow())
        self.conn.execute(
            "INSERT INTO p_prospect (practice_id, stage, created_at, updated_at) VALUES (?,?,?,?)",
            (practice_id, stage.value, now, now))
        return self.get_prospect(practice_id)  # type: ignore[return-value]

    def save_score(self, practice_id: int, score: float, reasons: list[dict[str, Any]]) -> None:
        now = to_iso(utcnow())
        self.conn.execute(
            "UPDATE p_prospect SET score=?, score_reasons=?, scored_at=?, updated_at=? WHERE practice_id=?",
            (score, json.dumps(reasons, ensure_ascii=False), now, now, practice_id))
