from __future__ import annotations

import sqlite3

from copilot.domain.models import Doctor, Practice, Specialty
from copilot.domain.timeutil import from_iso, to_iso, utcnow


def _practice(row: sqlite3.Row) -> Practice:
    d = dict(row)
    d["created_at"], d["updated_at"] = from_iso(d["created_at"]), from_iso(d["updated_at"])
    return Practice.model_validate(d)


class KnowledgeRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # -- specialties
    def upsert_specialty(self, code: str, name: str) -> Specialty:
        self.conn.execute(
            "INSERT INTO k_specialty (code, name) VALUES (?, ?) ON CONFLICT(code) DO UPDATE SET name = excluded.name",
            (code, name),
        )
        return self.get_specialty_by_code(code)  # type: ignore[return-value]

    def get_specialty_by_code(self, code: str) -> Specialty | None:
        row = self.conn.execute("SELECT * FROM k_specialty WHERE code = ?", (code,)).fetchone()
        return Specialty.model_validate(dict(row)) if row else None

    def get_specialty(self, specialty_id: int) -> Specialty | None:
        row = self.conn.execute("SELECT * FROM k_specialty WHERE id = ?", (specialty_id,)).fetchone()
        return Specialty.model_validate(dict(row)) if row else None

    def list_specialties(self) -> list[Specialty]:
        return [Specialty.model_validate(dict(r)) for r in self.conn.execute("SELECT * FROM k_specialty ORDER BY code")]

    # -- practices
    def insert_practice(self, p: Practice) -> Practice:
        now = to_iso(utcnow())
        cur = self.conn.execute(
            "INSERT INTO k_practice (name, street, plz, ort, ort_key, region, lat, lon, geo_precision, website_url,"
            " canonical_key, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (p.name, p.street, p.plz, p.ort, p.ort_key, p.region, p.lat, p.lon,
             p.geo_precision.value if p.geo_precision else None, p.website_url, p.canonical_key, now, now),
        )
        return self.get_practice(int(cur.lastrowid))  # type: ignore[return-value]

    def update_practice(self, p: Practice) -> Practice:
        self.conn.execute(
            "UPDATE k_practice SET name=?, street=?, plz=?, ort=?, ort_key=?, region=?, lat=?, lon=?, geo_precision=?,"
            " website_url=?, updated_at=? WHERE id=?",
            (p.name, p.street, p.plz, p.ort, p.ort_key, p.region, p.lat, p.lon,
             p.geo_precision.value if p.geo_precision else None, p.website_url, to_iso(utcnow()), p.id),
        )
        return self.get_practice(p.id)  # type: ignore[arg-type,return-value]

    def get_practice(self, practice_id: int) -> Practice | None:
        row = self.conn.execute("SELECT * FROM k_practice WHERE id = ?", (practice_id,)).fetchone()
        return _practice(row) if row else None

    def find_practice_by_key(self, canonical_key: str) -> Practice | None:
        row = self.conn.execute("SELECT * FROM k_practice WHERE canonical_key = ?", (canonical_key,)).fetchone()
        return _practice(row) if row else None

    def list_practices(self, *, region: str | None = None, ort_key: str | None = None) -> list[Practice]:
        sql, args = "SELECT * FROM k_practice WHERE 1=1", []
        if region:
            sql, args = sql + " AND region = ?", [*args, region]
        if ort_key:
            sql, args = sql + " AND ort_key = ?", [*args, ort_key]
        return [_practice(r) for r in self.conn.execute(sql + " ORDER BY name, id", args)]

    def add_practice_specialty(self, practice_id: int, specialty_id: int) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO k_practice_specialty (practice_id, specialty_id) VALUES (?,?)", (practice_id, specialty_id)
        )
        return cur.rowcount > 0

    def practice_specialties(self, practice_id: int) -> list[Specialty]:
        rows = self.conn.execute(
            "SELECT s.* FROM k_specialty s JOIN k_practice_specialty ps ON ps.specialty_id = s.id"
            " WHERE ps.practice_id = ? ORDER BY s.code", (practice_id,))
        return [Specialty.model_validate(dict(r)) for r in rows]

    def practices_with_specialties(self, specialty_codes: list[str]) -> list[Practice]:
        if not specialty_codes:
            return []
        marks = ",".join("?" * len(specialty_codes))
        rows = self.conn.execute(
            f"SELECT DISTINCT p.* FROM k_practice p JOIN k_practice_specialty ps ON ps.practice_id = p.id"
            f" JOIN k_specialty s ON s.id = ps.specialty_id WHERE s.code IN ({marks}) ORDER BY p.id", specialty_codes)
        return [_practice(r) for r in rows]

    # -- doctors
    def find_doctor_of_practice(self, practice_id: int, canonical_key: str) -> Doctor | None:
        row = self.conn.execute(
            "SELECT d.* FROM k_doctor d JOIN k_practice_doctor pd ON pd.doctor_id = d.id"
            " WHERE pd.practice_id = ? AND d.canonical_key = ?", (practice_id, canonical_key)).fetchone()
        return Doctor.model_validate(dict(row)) if row else None

    def insert_doctor(self, d: Doctor, practice_id: int) -> Doctor:
        cur = self.conn.execute(
            "INSERT INTO k_doctor (full_name, title, canonical_key) VALUES (?,?,?)", (d.full_name, d.title, d.canonical_key))
        doctor_id = int(cur.lastrowid)
        self.conn.execute("INSERT INTO k_practice_doctor (practice_id, doctor_id) VALUES (?,?)", (practice_id, doctor_id))
        return d.model_copy(update={"id": doctor_id})

    def doctors_of(self, practice_id: int) -> list[Doctor]:
        rows = self.conn.execute(
            "SELECT d.* FROM k_doctor d JOIN k_practice_doctor pd ON pd.doctor_id = d.id"
            " WHERE pd.practice_id = ? ORDER BY d.full_name", (practice_id,))
        return [Doctor.model_validate(dict(r)) for r in rows]

    def doctor_count(self, practice_id: int) -> int:
        return int(self.conn.execute(
            "SELECT count(*) FROM k_practice_doctor WHERE practice_id = ?", (practice_id,)).fetchone()[0])

    # -- origins (Provenienz der Existenz einer Praxis)
    def record_origin(self, practice_id: int, provider: str, source_ref: str) -> None:
        now = to_iso(utcnow())
        self.conn.execute(
            "INSERT INTO k_practice_origin (practice_id, provider, source_ref, first_seen_at, last_seen_at)"
            " VALUES (?,?,?,?,?) ON CONFLICT(practice_id, provider, source_ref) DO UPDATE SET last_seen_at = excluded.last_seen_at",
            (practice_id, provider, source_ref, now, now))

    def origins_of(self, practice_id: int) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT provider, source_ref, first_seen_at, last_seen_at FROM k_practice_origin WHERE practice_id = ?"
            " ORDER BY first_seen_at, id", (practice_id,)).fetchall()

    def doctor_keys_by_practice(self) -> dict[int, set[str]]:
        result: dict[int, set[str]] = {}
        for row in self.conn.execute(
                "SELECT pd.practice_id, d.canonical_key FROM k_practice_doctor pd JOIN k_doctor d ON d.id = pd.doctor_id"):
            result.setdefault(row[0], set()).add(row[1])
        return result
