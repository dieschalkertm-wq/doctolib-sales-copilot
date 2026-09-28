"""Fact-Referenzierung und Output-Validierung (verbindlich): Tatsachen brauchen Fact-IDs aus dem Kontext."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from copilot.llm.context import PracticeContext

_LITERAL = re.compile(r"https?://[^\s)\"']+|[\w.+-]+@[\w-]+\.[\w.-]+|(?:\+|00)\d[\d\s/().-]{6,}\d")


class StatementKind(str, Enum):
    FACT = "fact"              # Tatsachenbehauptung – nur mit Fact-ID(s) zulässig
    QUESTION = "question"      # Gesprächsfrage
    HYPOTHESIS = "hypothesis"  # Annahme/Vermutung – wird als „nicht belegt“ gekennzeichnet


class GroundedStatement(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=1000)
    kind: StatementKind
    fact_ids: list[int] = Field(default_factory=list)


class GroundedOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statements: list[GroundedStatement] = Field(min_length=1, max_length=50)


@dataclass(frozen=True)
class Violation:
    code: str
    statement_index: int


def validate_grounding(output: GroundedOutput, context: PracticeContext) -> list[Violation]:
    known = {f.id: f for f in context.facts}
    violations: list[Violation] = []
    for i, st in enumerate(output.statements):
        if any(fid not in known for fid in st.fact_ids):
            violations.append(Violation("unknown_fact_reference", i))
            continue
        if st.kind is StatementKind.FACT:
            if not st.fact_ids:
                violations.append(Violation("fact_without_reference", i))
                continue
            cited = " ".join(f"{known[fid].value} {known[fid].evidence or ''} {known[fid].source}" for fid in st.fact_ids)
            if any(lit not in cited for lit in _LITERAL.findall(st.text)):   # keine erfundenen URLs/Mails/Telefonnummern
                violations.append(Violation("literal_not_in_cited_facts", i))
    return violations


def render_grounded(output: GroundedOutput) -> str:
    lines = []
    for st in output.statements:
        refs = ",".join(f"F{i}" for i in st.fact_ids)
        if st.kind is StatementKind.FACT:
            lines.append(f"BELEGT [{refs}]: {st.text}")
        elif st.kind is StatementKind.HYPOTHESIS:
            lines.append(f"ANNAHME (nicht belegt){f' [{refs}]' if refs else ''}: {st.text}")
        else:
            lines.append(f"FRAGE: {st.text}")
    return "\n".join(lines)
