"""Merge-Queue (Persistenz). Mögliche Dubletten liegen hier, bis der Nutzer entscheidet – nie automatisches Merging."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from copilot.domain.timeutil import to_iso, utcnow
from copilot.knowledge.records import PracticeRecord


@dataclass
class MergeCandidate:
    id: int
    practice_id: int
    candidate_key: str
    provider: str
    source_ref: str
    record: PracticeRecord
    confidence: float
    reasons: list[str]
    status: str


def _row(r: sqlite3.Row) -> MergeCandidate:
    return MergeCandidate(r["id"], r["practice_id"], r["candidate_key"], r["provider"], r["source_ref"],
                          PracticeRecord.model_validate_json(r["payload"]), r["confidence"],
                          json.loads(r["reasons"]), r["status"])


class MergeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def enqueue(self, practice_id: int, candidate_key: str, provider: str, source_ref: str,
                record: PracticeRecord, confidence: float, reasons: list[str]) -> tuple[int, bool]:
        """(merge_id, neu_eingereiht). Bereits bekannte Paare (offen oder entschieden) werden nicht doppelt angelegt."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO k_merge_candidate (practice_id, candidate_key, provider, source_ref, payload,"
            " confidence, reasons, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (practice_id, candidate_key, provider, source_ref, record.model_dump_json(), round(confidence, 3),
             json.dumps(sorted(reasons)), to_iso(utcnow())))
        row = self.conn.execute(
            "SELECT id FROM k_merge_candidate WHERE practice_id = ? AND candidate_key = ? AND provider = ?",
            (practice_id, candidate_key, provider)).fetchone()
        return int(row[0]), cur.rowcount > 0

    def get(self, merge_id: int) -> MergeCandidate | None:
        row = self.conn.execute("SELECT * FROM k_merge_candidate WHERE id = ?", (merge_id,)).fetchone()
        return _row(row) if row else None

    def list(self, status: str | None = "open") -> list[MergeCandidate]:
        sql, args = "SELECT * FROM k_merge_candidate", []
        if status:
            sql, args = sql + " WHERE status = ?", [status]
        return [_row(r) for r in self.conn.execute(sql + " ORDER BY confidence DESC, id", args)]

    def siblings(self, candidate_key: str, provider: str) -> list[MergeCandidate]:
        rows = self.conn.execute(
            "SELECT * FROM k_merge_candidate WHERE candidate_key = ? AND provider = ? ORDER BY id", (candidate_key, provider))
        return [_row(r) for r in rows]

    def accepted_practice_for(self, candidate_key: str, provider: str) -> int | None:
        """Frühere Nutzerentscheidung 'gleiche Praxis' für genau diese Schreibweise/Quelle."""
        row = self.conn.execute(
            "SELECT practice_id FROM k_merge_candidate WHERE candidate_key = ? AND provider = ? AND status = 'same'"
            " ORDER BY id LIMIT 1", (candidate_key, provider)).fetchone()
        return int(row[0]) if row else None

    def known_pairs(self, candidate_key: str, provider: str) -> set[int]:
        return {int(r[0]) for r in self.conn.execute(
            "SELECT practice_id FROM k_merge_candidate WHERE candidate_key = ? AND provider = ?", (candidate_key, provider))}

    def set_status(self, merge_id: int, status: str) -> None:
        self.conn.execute("UPDATE k_merge_candidate SET status = ?, resolved_at = ? WHERE id = ?",
                          (status, to_iso(utcnow()), merge_id))
