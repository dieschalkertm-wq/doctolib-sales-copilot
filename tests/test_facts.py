import sqlite3
from datetime import timedelta

import pytest

from copilot.domain.enums import EntityType, FactStatus
from copilot.domain.models import FactDraft
from copilot.domain.timeutil import utcnow
from copilot.errors import NotFound
from copilot.knowledge.records import PracticeRecord
from copilot.research.facts import FactService


@pytest.fixture
def practice(app):
    return app.knowledge.upsert_practice(PracticeRecord(name="SYNTH Praxis", plz="66111", ort="Saarbrücken")).practice


@pytest.fixture
def facts(app):
    return FactService(app.research_repo, app.policies)


def test_fact_requires_existing_source(facts, practice):
    with pytest.raises(NotFound):
        facts.record(EntityType.PRACTICE, practice.id, FactDraft(key="k", value=1), source_id=999)
    # auch auf DB-Ebene: Fact ohne Quelle unmöglich
    with pytest.raises(sqlite3.IntegrityError):
        facts.repo.conn.execute(
            "INSERT INTO r_fact (subject_type, subject_id, key, value, source_id, confidence, observed_at)"
            " VALUES ('practice', 1, 'k', '1', NULL, 0.5, '2026-01-01T00:00:00+00:00')")


def test_provenance_and_statement(facts, practice):
    fact = facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key="online_booking_signal", value="x"))
    view = facts.view(fact)
    assert view.is_current and view.source.source_type.value == "manual"
    assert fact.stale_after == fact.observed_at + timedelta(days=90)
    assert view.statement().startswith("BELEGT:") and "manuelle Erfassung" in view.statement()


def test_stale_facts_are_marked_and_not_current(facts, practice):
    fact = facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key="doctolib_link_present", value=True))
    later = utcnow() + timedelta(days=91)
    view = facts.view(fact, now=later)
    assert view.is_stale and not view.is_current
    assert view.statement().startswith("VERALTET")
    profile = facts.profile(EntityType.PRACTICE, practice.id, now=later)
    assert not profile.current and len(profile.stale) == 1
    assert "doctolib_link_present" in profile.unknown_keys      # veraltet zählt wieder als "unbekannt/zu klären"


def test_new_fact_supersedes_old_and_claims_are_immutable(app, facts, practice):
    old = facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key="public_contact_phone", value=["a"]))
    new = facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key="public_contact_phone", value=["b"]))
    assert app.research_repo.get_fact(old.id).status is FactStatus.SUPERSEDED
    assert app.research_repo.get_fact(old.id).superseded_by == new.id
    assert [f.id for f in app.research_repo.facts_for(EntityType.PRACTICE, practice.id)] == [new.id]
    for column in ("value", "source_id", "observed_at", "stale_after", "key"):
        with pytest.raises(sqlite3.IntegrityError):
            app.conn.execute(f"UPDATE r_fact SET {column} = {column} WHERE id = ?", (new.id,))


def test_source_provenance_is_immutable(app, facts, practice):
    fact = facts.record_manual(EntityType.PRACTICE, practice.id, FactDraft(key="k", value=1))
    with pytest.raises(sqlite3.IntegrityError):
        app.conn.execute("UPDATE r_source SET retrieved_at = '2000-01-01T00:00:00+00:00' WHERE id = ?", (fact.source_id,))


def test_unknowns_listed_for_practice_without_facts(facts, practice):
    profile = facts.profile(EntityType.PRACTICE, practice.id)
    assert not profile.current and profile.unknown_keys == facts.policies.expected_fact_keys
