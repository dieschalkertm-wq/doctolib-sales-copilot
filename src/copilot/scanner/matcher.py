"""ExistingDataMatcher: gleicht Kandidaten mit bereits vorhandenen Praxen ab – bewusst KONSERVATIV.

Ergebnis ist genau eines von:
  EXACT     eindeutiger Treffer -> Kandidat wird an die vorhandene Praxis angehängt (nur Lücken füllen)
  POSSIBLE  möglicher Treffer   -> Merge-Queue zur Prüfung durch den Nutzer; es wird NICHTS zusammengeführt
  NONE      kein Treffer        -> neue Praxis
'EXACT' entsteht ausschließlich aus harten, erklärbaren Regeln (siehe COMBOS). Reines Namens-Fuzzy-Matching führt nie
zu EXACT. Jede Entscheidung trägt Confidence und maschinenlesbare Gründe.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from urllib.parse import urlsplit

from copilot.domain.models import Practice
from copilot.domain.normalize import doctor_key, fold, fold_street, practice_key
from copilot.knowledge.records import PracticeRecord
from copilot.storage.knowledge import KnowledgeRepository
from copilot.storage.merge import MergeRepository

SIMILAR_NAME_THRESHOLD = 0.85
MAX_POSSIBLE = 3

_GENERIC = {"praxis", "dr", "med", "dipl", "prof", "gemeinschaftspraxis", "und", "fuer", "der", "die", "das",
            "gmbh", "gbr", "mvz", "facharzt", "fachaerztin", "arzt", "aerztin", "aerzte", "zentrum", "privat"}

# (benötigte Signale, Confidence, Art). Höchste zutreffende Confidence gewinnt.
COMBOS: list[tuple[frozenset[str], float, str]] = [
    (frozenset({"same_key"}), 1.00, "exact"),
    (frozenset({"same_website", "same_street"}), 0.97, "exact"),
    (frozenset({"same_name", "same_plz"}), 0.80, "possible"),
    (frozenset({"same_plz", "same_street"}), 0.75, "possible"),      # gleiche Adresse, anderer Name (MVZ, Nachfolge …)
    (frozenset({"similar_name", "same_plz"}), 0.65, "possible"),
    (frozenset({"same_website"}), 0.65, "possible"),                 # gleiche Website, andere Adresse (Filialen …)
    (frozenset({"same_name", "same_ort"}), 0.60, "possible"),
    (frozenset({"shared_doctor", "same_ort"}), 0.55, "possible"),
    (frozenset({"similar_name", "same_ort"}), 0.50, "possible"),
]


class MatchKind(str, Enum):
    EXACT = "exact"
    POSSIBLE = "possible"
    NONE = "none"

    def __str__(self) -> str:
        return self.value


@dataclass
class MatchResult:
    kind: MatchKind
    candidates: list[tuple[int, float, list[str]]] = field(default_factory=list)  # (practice_id, confidence, reasons)

    @property
    def practice_id(self) -> int | None:
        return self.candidates[0][0] if self.kind is MatchKind.EXACT else None

    @property
    def confidence(self) -> float:
        return self.candidates[0][1] if self.candidates else 0.0


def name_tokens(name: str) -> list[str]:
    tokens = [t for t in fold(name).split() if t not in _GENERIC]
    return tokens or fold(name).split()


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, " ".join(sorted(name_tokens(a))), " ".join(sorted(name_tokens(b)))).ratio()


def website_host(url: str | None) -> str | None:
    if not url:
        return None
    host = (urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    return host.removeprefix("www.") or None


class ExistingDataMatcher:
    def __init__(self, knowledge: KnowledgeRepository, merge: MergeRepository):
        self.knowledge, self.merge = knowledge, merge
        self._practices: dict[int, Practice] = {}
        self._doctors: dict[int, set[str]] = {}
        self._by_key: dict[str, list[int]] = {}
        self._by_host: dict[str, list[int]] = {}
        self._by_plz: dict[str, list[int]] = {}
        self._by_ort: dict[str, list[int]] = {}
        self._by_doctor: dict[str, list[int]] = {}

    def load(self) -> "ExistingDataMatcher":
        self._practices.clear()
        for index in (self._by_key, self._by_host, self._by_plz, self._by_ort, self._by_doctor):
            index.clear()
        self._doctors = self.knowledge.doctor_keys_by_practice()
        for practice in self.knowledge.list_practices():
            self.add(practice)
        return self

    def add(self, practice: Practice) -> None:
        pid: int = practice.id  # type: ignore[assignment]
        self._practices[pid] = practice
        self._by_key.setdefault(practice.canonical_key, []).append(pid)
        if host := website_host(practice.website_url):
            self._by_host.setdefault(host, []).append(pid)
        if practice.plz:
            self._by_plz.setdefault(practice.plz, []).append(pid)
        if practice.ort_key:
            self._by_ort.setdefault(practice.ort_key, []).append(pid)
        for key in self._doctors.get(pid, set()):
            self._by_doctor.setdefault(key, []).append(pid)

    def add_doctors(self, practice_id: int, records: list) -> None:
        """Nach dem Anlegen/Anhängen von Ärzten den Index aktualisieren (ohne DB-Abfrage)."""
        keys = self._doctors.setdefault(practice_id, set())
        for d in records:
            key = doctor_key(d.full_name)
            if key and key not in keys:
                keys.add(key)
                self._by_doctor.setdefault(key, []).append(practice_id)

    # ------------------------------------------------------------------------------------------
    def _signals(self, rec: PracticeRecord, key: str, existing: Practice, doctor_keys: set[str]) -> set[str]:
        signals: set[str] = set()
        if key == existing.canonical_key:
            signals.add("same_key")
        host = website_host(rec.website)
        if host and host == website_host(existing.website_url):
            signals.add("same_website")
        street, ex_street = fold_street(rec.street), fold_street(existing.street)
        if street and street == ex_street:
            signals.add("same_street")
        if rec.plz and rec.plz == existing.plz:
            signals.add("same_plz")
        if rec.ort and fold(rec.ort) == existing.ort_key:
            signals.add("same_ort")
        if sorted(name_tokens(rec.name)) == sorted(name_tokens(existing.name)):
            signals.add("same_name")
        elif name_similarity(rec.name, existing.name) >= SIMILAR_NAME_THRESHOLD:
            signals.add("similar_name")
        if doctor_keys & self._doctors.get(existing.id, set()):  # type: ignore[arg-type]
            signals.add("shared_doctor")
        return signals

    def match(self, rec: PracticeRecord, provider: str) -> MatchResult:
        key = practice_key(rec.name, rec.plz, rec.street)

        accepted = self.merge.accepted_practice_for(key, provider)   # frühere Nutzerentscheidung „gleiche Praxis“
        if accepted is not None and accepted in self._practices:
            return MatchResult(MatchKind.EXACT, [(accepted, 1.0, ["manual_merge_decision"])])

        pool: set[int] = set(self._by_key.get(key, []))
        if host := website_host(rec.website):
            pool |= set(self._by_host.get(host, []))
        if rec.plz:
            pool |= set(self._by_plz.get(rec.plz, []))
        if rec.ort:
            pool |= set(self._by_ort.get(fold(rec.ort), []))
        doctor_keys = {doctor_key(d.full_name) for d in rec.doctors}
        for dk in doctor_keys:
            pool |= set(self._by_doctor.get(dk, []))

        decided_different = {c.practice_id for c in self.merge.siblings(key, provider) if c.status == "different"}
        exact: list[tuple[int, float, list[str]]] = []
        possible: list[tuple[int, float, list[str]]] = []
        for pid in sorted(pool):
            if pid in decided_different:
                continue
            signals = self._signals(rec, key, self._practices[pid], doctor_keys)
            best = max(((conf, kind, need) for need, conf, kind in COMBOS if need <= signals),
                       key=lambda c: c[0], default=None)
            if best is None:
                continue
            conf, kind, _ = best
            (exact if kind == "exact" else possible).append((pid, conf, sorted(signals)))

        if len(exact) == 1:
            return MatchResult(MatchKind.EXACT, exact)
        if len(exact) > 1:   # mehrdeutig -> nie automatisch entscheiden
            return MatchResult(MatchKind.POSSIBLE, [(p, c, r + ["ambiguous_exact"]) for p, c, r in exact][:MAX_POSSIBLE])
        if possible:
            possible.sort(key=lambda c: (-c[1], c[0]))
            return MatchResult(MatchKind.POSSIBLE, possible[:MAX_POSSIBLE])
        return MatchResult(MatchKind.NONE)
