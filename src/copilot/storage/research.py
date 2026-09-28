from __future__ import annotations

import json
import sqlite3

from copilot.domain.enums import EntityType, FactStatus, ResearchStatus
from copilot.domain.models import Event, Fact, Research, Source
from copilot.domain.timeutil import from_iso, to_iso


def _opt(value: str | None):
    return from_iso(value) if value else None


def _fact(row: sqlite3.Row) -> Fact:
    d = dict(row)
    d["value"] = json.loads(d["value"])
    d["observed_at"], d["stale_after"] = from_iso(d["observed_at"]), _opt(d["stale_after"])
    return Fact.model_validate(d)


def _source(row: sqlite3.Row) -> Source:
    d = dict(row)
    d["retrieved_at"], d["published_at"] = from_iso(d["retrieved_at"]), _opt(d["published_at"])
    return Source.model_validate(d)


class ResearchRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -- sources
    def insert_source(self, s: Source) -> Source:
        cur = self.conn.execute(
            "INSERT INTO r_source (source_type, url, publisher, retrieved_at, published_at, content_hash,"
            " robots_status, tos_ref, reliability, raw_ref) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (s.source_type.value, s.url, s.publisher, to_iso(s.retrieved_at),
             to_iso(s.published_at) if s.published_at else None, s.content_hash, s.robots_status.value,
             s.tos_ref, s.reliability, s.raw_ref))
        return s.model_copy(update={"id": int(cur.lastrowid)})

    def get_source(self, source_id: int) -> Source | None:
        row = self.conn.execute("SELECT * FROM r_source WHERE id = ?", (source_id,)).fetchone()
        return _source(row) if row else None

    # -- research runs
    def start_research(self, r: Research) -> Research:
        cur = self.conn.execute(
            "INSERT INTO r_research (subject_type, subject_id, kind, provider, status, started_at) VALUES (?,?,?,?,?,?)",
            (r.subject_type.value, r.subject_id, r.kind, r.provider, ResearchStatus.STARTED.value, to_iso(r.started_at)))
        return r.model_copy(update={"id": int(cur.lastrowid)})

    def finish_research(self, research_id: int, status: ResearchStatus, finished_at, error_code: str | None = None) -> None:
        self.conn.execute(
            "UPDATE r_research SET status=?, finished_at=?, error_code=? WHERE id=?",
            (status.value, to_iso(finished_at), error_code, research_id))

    def list_research(self, subject_type: EntityType, subject_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM r_research WHERE subject_type=? AND subject_id=? ORDER BY id DESC",
            (subject_type.value, subject_id)).fetchall()

    # -- facts
    def insert_fact(self, f: Fact) -> Fact:
        cur = self.conn.execute(
            "INSERT INTO r_fact (subject_type, subject_id, key, value, source_id, research_id, confidence, evidence,"
            " observed_at, stale_after, status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (f.subject_type.value, f.subject_id, f.key, json.dumps(f.value, ensure_ascii=False, sort_keys=True),
             f.source_id, f.research_id, f.confidence, f.evidence, to_iso(f.observed_at),
             to_iso(f.stale_after) if f.stale_after else None, f.status.value))
        return f.model_copy(update={"id": int(cur.lastrowid)})

    def get_fact(self, fact_id: int) -> Fact | None:
        row = self.conn.execute("SELECT * FROM r_fact WHERE id = ?", (fact_id,)).fetchone()
        return _fact(row) if row else None

    def facts_for(self, subject_type: EntityType, subject_id: int, *, key: str | None = None,
                  active_only: bool = True) -> list[Fact]:
        sql = "SELECT * FROM r_fact WHERE subject_type=? AND subject_id=?"
        args: list = [subject_type.value, subject_id]
        if key:
            sql, args = sql + " AND key=?", [*args, key]
        if active_only:
            sql += " AND status='active'"
        return [_fact(r) for r in self.conn.execute(sql + " ORDER BY key, id", args)]

    def set_fact_status(self, fact_id: int, status: FactStatus, superseded_by: int | None = None) -> None:
        self.conn.execute("UPDATE r_fact SET status=?, superseded_by=? WHERE id=?", (status.value, superseded_by, fact_id))

    # -- events (Struktur für Phase 3 vorbereitet)
    def insert_event(self, e: Event) -> Event:
        cur = self.conn.execute(
            "INSERT INTO r_event (name, date_from, date_to, ort, lat, lon, url, registration_deadline, distance_km, source_id)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (e.name, e.date_from, e.date_to, e.ort, e.lat, e.lon, e.url, e.registration_deadline, e.distance_km, e.source_id))
        event_id = int(cur.lastrowid)
        for sid in e.specialty_ids:
            self.conn.execute("INSERT INTO r_event_specialty (event_id, specialty_id) VALUES (?,?)", (event_id, sid))
        return e.model_copy(update={"id": event_id})

    def list_events(self) -> list[Event]:
        events = []
        for r in self.conn.execute("SELECT * FROM r_event ORDER BY date_from, id").fetchall():
            d = dict(r)
            d["specialty_ids"] = [x[0] for x in self.conn.execute(
                "SELECT specialty_id FROM r_event_specialty WHERE event_id=?", (d["id"],))]
            events.append(Event.model_validate(d))
        return events
