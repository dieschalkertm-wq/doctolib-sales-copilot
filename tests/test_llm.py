import json
from datetime import timedelta

import pytest

from copilot.config import LLMPolicy
from copilot.domain.enums import EntityType
from copilot.domain.models import FactDraft
from copilot.domain.timeutil import utcnow
from copilot.errors import LLMError, PolicyViolation
from copilot.knowledge.records import DoctorRecord, PracticeRecord
from copilot.llm.context import ContextBuilder
from copilot.llm.gateway import LLMGateway, LLMTask
from copilot.llm.grounding import GroundedOutput, render_grounded, validate_grounding


class FakeProvider:
    name, is_external = "fake", False

    def __init__(self, payload, external=False):
        self.payload, self.is_external, self.requests = payload, external, []

    def complete(self, request):
        self.requests.append(request)
        return self.payload if isinstance(self.payload, str) else json.dumps(self.payload)


@pytest.fixture
def practice(app):
    p = app.knowledge.upsert_practice(PracticeRecord(
        name="SYNTH Praxis Alpha", plz="66111", ort="Saarbrücken", specialty_labels=["Hausarzt"],
        doctors=[DoctorRecord(full_name="Erika Testfrau", title="Dr.")], website="synth-alpha.invalid")).practice
    app.pipeline.mark_customer(p.id)                       # interne Pipeline-Information: darf NIE in den Kontext
    return p


@pytest.fixture
def facts(app, practice):
    booking = app.facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(
        key="online_booking_signal", value=["Terminland"], evidence="https://www.terminland.de/synth"))
    phone = app.facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(
        key="public_contact_phone", value=["+49 681 000000"]))
    return booking, phone


def gateway(app, provider, **policy):
    return LLMGateway(LLMPolicy(**{"enabled": True, **policy}), provider, app.audit)


def context(app, practice, **policy):
    return ContextBuilder(app.knowledge_repo, app.facts, LLMPolicy(**policy)).for_practice(practice.id)


def test_context_is_minimal_and_free_of_internal_data(app, practice, facts):
    ctx = context(app, practice)
    text = ctx.render()
    assert ctx.label == f"Praxis #{practice.id}" and "SYNTH" not in text          # Name/Ärzte standardmäßig draußen
    assert "Erika" not in text and "Kunde" not in text and "customer" not in text.lower()
    assert {f.key for f in ctx.facts} == {"online_booking_signal"}                # Kontaktdaten-Fact ausgeschlossen
    assert f"[F{facts[0].id}]" in text and "Terminland" in text and "abgerufen" in text
    named = context(app, practice, include_practice_name=True, include_doctor_names=True, include_contact_data=True)
    assert "SYNTH Praxis Alpha" in named.render() and "Erika Testfrau" in named.render() and len(named.facts) == 2


def test_stale_facts_never_reach_the_llm(app, practice, facts):
    ctx = ContextBuilder(app.knowledge_repo, app.facts, LLMPolicy()).for_practice(practice.id, now=utcnow() + timedelta(days=400))
    assert ctx.facts == ()


def test_gateway_is_off_by_default_and_blocks_external(app, practice, facts):
    ctx = context(app, practice)
    with pytest.raises(PolicyViolation) as exc:
        LLMGateway(LLMPolicy(), FakeProvider({}), app.audit).run(LLMTask.PRACTICE_PROFILE, ctx)
    assert exc.value.code == "llm_disabled"
    with pytest.raises(LLMError) as exc:
        gateway(app, None).run(LLMTask.PRACTICE_PROFILE, ctx)
    assert exc.value.code == "llm_no_provider"
    provider = FakeProvider({}, external=True)
    with pytest.raises(PolicyViolation) as exc:
        gateway(app, provider).run(LLMTask.PRACTICE_PROFILE, ctx)
    assert exc.value.code == "llm_external_not_allowed" and provider.requests == []   # nichts wurde gesendet


def test_pii_in_context_or_input_blocks_the_call(app, practice, facts):
    provider = FakeProvider({})
    with pytest.raises(PolicyViolation) as exc:
        gateway(app, provider).run(LLMTask.OBJECTION_COACH, context(app, practice, include_contact_data=True))
    assert exc.value.code == "pii_in_context"
    with pytest.raises(PolicyViolation) as exc:
        gateway(app, provider).run(LLMTask.OBJECTION_COACH, context(app, practice), user_input="Mail an max@example.com")
    assert exc.value.code == "pii_in_user_input" and provider.requests == []


def test_grounded_output_passes_and_is_rendered_with_references(app, practice, facts):
    fid = facts[0].id
    provider = FakeProvider({"statements": [
        {"text": "Es ist eine Online-Terminbuchung über Terminland erkennbar.", "kind": "fact", "fact_ids": [fid]},
        {"text": "Wie zufrieden ist die Praxis mit der aktuellen Lösung?", "kind": "question"},
        {"text": "Die Praxis könnte offen für Integration sein.", "kind": "hypothesis"}]})
    output = gateway(app, provider).run(LLMTask.MEETING_BRIEFING, context(app, practice),
                                        user_input="Der Arzt sagt, wir haben bereits eine Lösung.")
    text = render_grounded(output)
    assert f"BELEGT [F{fid}]" in text and "ANNAHME (nicht belegt)" in text and "FRAGE:" in text
    request = provider.requests[0]
    assert "Praxis #" in request.context_text and "SYNTH" not in request.context_text
    assert "Erfinde keine Informationen" in request.system_rules


@pytest.mark.parametrize("statement,code", [
    ({"text": "Die Praxis nutzt bereits doctolib.", "kind": "fact"}, "fact_without_reference"),
    ({"text": "Die Praxis nutzt Terminland.", "kind": "fact", "fact_ids": [99999]}, "unknown_fact_reference"),
    ({"text": "Buchung unter https://erfunden.example/termin", "kind": "fact", "fact_ids": "FID"}, "literal_not_in_cited_facts"),
])
def test_ungrounded_output_is_rejected(app, practice, facts, statement, code):
    if statement.get("fact_ids") == "FID":
        statement = {**statement, "fact_ids": [facts[0].id]}
    provider = FakeProvider({"statements": [statement]})
    with pytest.raises(LLMError) as exc:
        gateway(app, provider).run(LLMTask.PRACTICE_PROFILE, context(app, practice))
    assert exc.value.code == "ungrounded_output" and code in exc.value.details["violations"][0]


def test_cited_literal_from_fact_is_allowed(app, practice, facts):
    ctx = context(app, practice)
    output = GroundedOutput.model_validate({"statements": [
        {"text": "Buchung über https://www.terminland.de/synth", "kind": "fact", "fact_ids": [facts[0].id]}]})
    assert validate_grounding(output, ctx) == []


@pytest.mark.parametrize("raw", ["kein json", "{}", '{"statements": []}', '{"statements": [{"text": "x", "kind": "fact", "extra": 1}]}'])
def test_invalid_model_output_is_rejected(app, practice, facts, raw):
    with pytest.raises(LLMError) as exc:
        gateway(app, FakeProvider(raw)).run(LLMTask.PRACTICE_PROFILE, context(app, practice))
    assert exc.value.code == "llm_output_invalid"


def test_llm_audit_contains_metadata_only(app, practice, facts):
    provider = FakeProvider({"statements": [{"text": "Frage?", "kind": "question"}]})
    gateway(app, provider).run(LLMTask.DRAFT_MESSAGE, context(app, practice))
    with pytest.raises(LLMError):
        gateway(app, FakeProvider("kaputt")).run(LLMTask.DRAFT_MESSAGE, context(app, practice))
    events = [json.loads(r["details"]) for r in app.audit.tail(5) if r["event_type"] == "llm.call"]
    assert {e["status"] for e in events} == {"succeeded", "rejected"}
    assert all(set(e) <= {"task", "status", "fact_count", "provider", "error_code"} for e in events)
    assert "Frage" not in json.dumps(events)


def test_context_size_is_capped(app, practice):
    for i in range(6):
        app.facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key=f"k{i}", value=i + 1))
    assert len(context(app, practice, max_facts=3).facts) == 3
