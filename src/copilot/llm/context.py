"""Kontext für LLM-Aufgaben: ausschließlich belegte, aktuelle Facts EINER Praxis mit IDs und Quellen.

Bewusst NICHT enthalten: Datenbankauszüge, Kundenlisten, Pipeline-Status, Notizen, Netzwerkbeziehungen, andere Praxen,
Kontaktdaten (Standard). Der Kontext wird nur hier gebaut; das Gateway akzeptiert keine freien Datenstrukturen."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from copilot.config import LLMPolicy
from copilot.domain.enums import EntityType
from copilot.errors import NotFound
from copilot.research.facts import FactService
from copilot.storage.knowledge import KnowledgeRepository

SENSITIVE_FACT_KEYS = frozenset({"public_contact_phone", "public_contact_email"})


@dataclass(frozen=True)
class ContextFact:
    id: int
    key: str
    value: Any
    source: str
    retrieved_at: str
    evidence: str | None

    def text(self) -> str:
        return f"[F{self.id}] {self.key} = {self.value!r} (Quelle: {self.source}, abgerufen {self.retrieved_at})"


@dataclass(frozen=True)
class PracticeContext:
    practice_id: int
    label: str
    specialties: tuple[str, ...]
    ort: str | None
    doctors: tuple[str, ...]
    facts: tuple[ContextFact, ...]

    @property
    def fact_ids(self) -> frozenset[int]:
        return frozenset(f.id for f in self.facts)

    def render(self) -> str:
        lines = [f"Praxis: {self.label}",
                 f"Fachrichtung: {', '.join(self.specialties) or 'unbekannt'}",
                 f"Ort: {self.ort or 'unbekannt'}"]
        if self.doctors:
            lines.append(f"Ärzte: {', '.join(self.doctors)}")
        lines.append("Belegte Facts (nur diese dürfen als Tatsachen genannt werden):")
        lines += [f"  {f.text()}" for f in self.facts] or ["  (keine)"]
        return "\n".join(lines)


class ContextBuilder:
    def __init__(self, knowledge: KnowledgeRepository, facts: FactService, policy: LLMPolicy):
        self.knowledge, self.facts, self.policy = knowledge, facts, policy

    def for_practice(self, practice_id: int, now: datetime | None = None) -> PracticeContext:
        practice = self.knowledge.get_practice(practice_id)
        if practice is None:
            raise NotFound("Praxis nicht gefunden", code="practice_not_found")
        profile = self.facts.profile(EntityType.PRACTICE, practice_id, now)   # nur aktuelle Facts; veraltete bleiben draußen
        facts = [ContextFact(v.fact.id, v.fact.key, v.fact.value, v.source.url or v.source.publisher or v.source.source_type.value,  # type: ignore[arg-type]
                             v.source.retrieved_at.date().isoformat(), v.fact.evidence)
                 for v in profile.current
                 if self.policy.include_contact_data or v.fact.key not in SENSITIVE_FACT_KEYS]
        facts.sort(key=lambda f: f.id, reverse=True)   # neueste zuerst, dann begrenzen
        facts = sorted(facts[: self.policy.max_facts], key=lambda f: f.id)
        return PracticeContext(
            practice_id=practice_id,
            label=practice.name if self.policy.include_practice_name else f"Praxis #{practice_id}",
            specialties=tuple(s.name for s in self.knowledge.practice_specialties(practice_id)),
            ort=practice.ort,
            doctors=tuple(d.full_name for d in self.knowledge.doctors_of(practice_id)) if self.policy.include_doctor_names else (),
            facts=tuple(facts))
