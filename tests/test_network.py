import sqlite3

import pytest

from copilot.domain.enums import EntityType, RelationOrigin
from copilot.domain.models import FactDraft
from copilot.errors import IntegrityViolation, NotFound
from copilot.knowledge.records import PracticeRecord
from copilot.research.facts import FactService


def add(app, name, ort, plz, spec):
    return app.knowledge.upsert_practice(
        PracticeRecord(name=name, ort=ort, plz=plz, specialty_labels=[spec])).practice


@pytest.fixture
def world(app):
    gp = add(app, "SYNTH GP", "Saarbrücken", "66111", "Hausarzt")
    cardio = add(app, "SYNTH Cardio", "Saarbrücken", "66113", "Kardiologie")
    ortho = add(app, "SYNTH Ortho", "Völklingen", "66333", "Orthopädie")
    far = add(app, "SYNTH Far Cardio", "Trier", "54290", "Kardiologie")        # außerhalb 25 km
    other = add(app, "SYNTH Psych", "Saarbrücken", "66111", "Psychiatrie")     # keine Regel-Zielfachrichtung
    return dict(gp=gp, cardio=cardio, ortho=ortho, far=far, other=other)


def test_derive_is_rule_based_radius_limited_and_idempotent(app, world):
    result = app.network.derive_for_practice(world["gp"].id, radius_km=25)
    assert (result.created, result.existing) == (2, 0)
    rels = app.network_repo.for_entity(EntityType.PRACTICE, world["gp"].id, direction="out")
    assert {r.to_id for r in rels} == {world["cardio"].id, world["ortho"].id}
    assert all(r.origin is RelationOrigin.DERIVED and r.rule_id.startswith("referral_rules.v1:") for r in rels)
    assert all(r.fact_id is None for r in rels)
    again = app.network.derive_for_practice(world["gp"].id, radius_km=25)
    assert (again.created, again.existing) == (0, 2)


def test_derived_is_never_described_as_observed(app, world):
    app.network.derive_for_practice(world["gp"].id)
    for rel in app.network_repo.for_entity(EntityType.PRACTICE, world["gp"].id):
        text = app.network.describe(rel)
        assert text.startswith("ABGELEITET") and "BEOBACHTET" not in text and "nicht belegt" in text


def test_observed_requires_active_fact_of_endpoint(app, world):
    facts = FactService(app.research_repo, app.policies)
    gp, cardio = world["gp"], world["cardio"]
    with pytest.raises(NotFound):
        app.network.record_observed(gp.id, cardio.id, fact_id=999)
    fact = facts.record_manual(EntityType.PRACTICE, gp.id, FactDraft(key="refers_to_practice", value="belegt"))
    rel = app.network.record_observed(gp.id, cardio.id, fact.id)
    text = app.network.describe(rel)
    assert text.startswith("BEOBACHTET") and f"Fact #{fact.id}" in text
    with pytest.raises(IntegrityViolation) as exc:
        app.network.record_observed(gp.id, world["ortho"].id, facts.record_manual(
            EntityType.PRACTICE, world["far"].id, FactDraft(key="x", value=1)).id)
    assert exc.value.code == "fact_subject_mismatch"
    # superseded Fact taugt nicht als Beleg
    facts.record_manual(EntityType.PRACTICE, gp.id, FactDraft(key="refers_to_practice", value="neu"))
    with pytest.raises(IntegrityViolation) as exc:
        app.network.record_observed(gp.id, world["ortho"].id, fact.id)
    assert exc.value.code == "fact_not_active"


def test_db_refuses_observed_without_fact_and_derived_without_rule(app, world):
    sql = ("INSERT INTO k_network_relationship (from_type, from_id, to_type, to_id, rel_type, origin, fact_id, rule_id, created_at)"
           " VALUES ('practice', ?, 'practice', ?, 'refers_to', ?, ?, ?, 'now')")
    gp, c = world["gp"].id, world["cardio"].id
    with pytest.raises(sqlite3.IntegrityError):
        app.conn.execute(sql, (gp, c, "observed", None, None))
    with pytest.raises(sqlite3.IntegrityError):
        app.conn.execute(sql, (gp, c, "derived", None, None))


def test_manual_relationship_is_labelled_manual(app, world):
    rel = app.network.record_manual(world["gp"].id, world["cardio"].id, note="aus Gespräch")
    assert app.network.describe(rel) == "MANUELL erfasst"


def test_derive_without_specialty_reports(app):
    p = app.knowledge.upsert_practice(PracticeRecord(name="SYNTH ohne", ort="Trier", plz="54290")).practice
    assert app.network.derive_for_practice(p.id).no_specialty
