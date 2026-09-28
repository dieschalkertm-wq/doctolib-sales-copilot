"""LLM-Gateway (VORBEREITET, standardmäßig aus): einziger Weg zu einem Sprachmodell.

Garantien:
  * nur ein typisierter PracticeContext (belegte Facts mit IDs) – nie „die ganze Datenbank“
  * Policy-Gate: llm.enabled, externe Anbieter nur mit llm.allow_external (interne Klärung offen)
  * PII-Prüfung des Kontexts und der Nutzereingabe (Mail/Telefon/Tokens) vor jedem Aufruf
  * Antwort muss valides JSON im GroundedOutput-Schema sein; Tatsachen ohne gültige Fact-ID werden abgelehnt
  * Audit nur mit Metadaten (Task, Anbieter, Status, Anzahl Facts) – nie Inhalte
Es ist absichtlich KEIN konkreter Anbieter angebunden."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from pydantic import ValidationError

from copilot.config import LLMPolicy
from copilot.errors import LLMError, PolicyViolation
from copilot.llm.context import PracticeContext
from copilot.llm.grounding import GroundedOutput, validate_grounding
from copilot.security.redaction import redact
from copilot.storage.audit import AuditLog

MAX_USER_INPUT = 2000

SYSTEM_RULES = (
    "Du unterstützt einen Vertriebsmitarbeiter. Nutze AUSSCHLIESSLICH die unten gelisteten Facts. "
    "Antworte nur mit JSON im vorgegebenen Schema. Aussagen vom Typ 'fact' müssen mindestens eine Fact-ID aus dem "
    "Kontext zitieren und dürfen keine URLs, E-Mail-Adressen oder Telefonnummern enthalten, die nicht in den zitierten "
    "Facts stehen. Alles Nicht-Belegte ist 'hypothesis' oder 'question'. Erfinde keine Informationen; was fehlt, "
    "benenne als offene Frage."
)


class LLMTask(str, Enum):
    PRACTICE_PROFILE = "practice_profile"
    MEETING_BRIEFING = "meeting_briefing"
    OBJECTION_COACH = "objection_coach"
    DRAFT_MESSAGE = "draft_message"      # nur Entwurf – Versand ist Level 3 und nicht Teil des Gateways


@dataclass(frozen=True)
class LLMRequest:
    task: LLMTask
    system_rules: str
    context_text: str
    user_input: str | None
    output_schema: dict[str, Any]


class LLMProvider(Protocol):
    name: str
    is_external: bool

    def complete(self, request: LLMRequest) -> str:
        """Liefert die rohe Modellantwort (JSON-Text)."""


class LLMGateway:
    def __init__(self, policy: LLMPolicy, provider: LLMProvider | None, audit: AuditLog):
        self.policy, self.provider, self.audit = policy, provider, audit

    def run(self, task: LLMTask, context: PracticeContext, *, user_input: str | None = None) -> GroundedOutput:
        try:
            output = self._run(task, context, user_input)
        except (PolicyViolation, LLMError) as exc:
            self._audit(task, "rejected", len(context.facts), exc.code)
            raise
        self._audit(task, "succeeded", len(context.facts), None)
        return output

    def _run(self, task: LLMTask, context: PracticeContext, user_input: str | None) -> GroundedOutput:
        if not self.policy.enabled:
            raise PolicyViolation("LLM-Gateway ist ausgeschaltet (config/policies.yaml: llm.enabled)", code="llm_disabled")
        if self.provider is None:
            raise LLMError("Kein LLM-Anbieter angebunden", code="llm_no_provider")
        if self.provider.is_external and not self.policy.allow_external:
            raise PolicyViolation("Externe LLM-Anbieter sind nicht freigegeben (llm.allow_external)",
                                  code="llm_external_not_allowed")
        if len(context.facts) > self.policy.max_facts:
            raise PolicyViolation("Kontext überschreitet die erlaubte Fact-Anzahl", code="context_too_large")
        text = context.render()
        if redact(text) != text:
            raise PolicyViolation("Kontext enthält personenbezogene Kontaktdaten/Secrets", code="pii_in_context")
        if user_input is not None:
            if len(user_input) > MAX_USER_INPUT:
                raise PolicyViolation("Nutzereingabe zu lang", code="user_input_too_long")
            if redact(user_input) != user_input:
                raise PolicyViolation("Nutzereingabe enthält Kontaktdaten/Secrets", code="pii_in_user_input")

        raw = self.provider.complete(LLMRequest(task, SYSTEM_RULES, text, user_input, GroundedOutput.model_json_schema()))
        try:
            output = GroundedOutput.model_validate(json.loads(raw))
        except (ValueError, ValidationError) as exc:
            raise LLMError("Antwort entspricht nicht dem Schema", code="llm_output_invalid") from exc
        violations = validate_grounding(output, context)
        if violations:
            raise LLMError("Antwort enthält nicht belegte Tatsachen", code="ungrounded_output",
                           details={"violations": [f"{v.code}@{v.statement_index}" for v in violations]})
        return output

    def _audit(self, task: LLMTask, status: str, fact_count: int, error_code: str | None) -> None:
        details: dict[str, Any] = {"task": task.value, "status": status, "fact_count": fact_count,
                                   "provider": self.provider.name if self.provider else "none"}
        if error_code:
            details["error_code"] = error_code
        self.audit.record("llm.call", "LLM-Aufruf", details=details)
