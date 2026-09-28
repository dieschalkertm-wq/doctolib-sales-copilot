from datetime import timedelta

import pytest

from copilot.connectors.imports.csv_practices import CsvPracticeSource
from copilot.connectors.imports.service import PracticeImporter
from copilot.domain.enums import EntityType
from copilot.domain.models import FactDraft
from copilot.domain.timeutil import utcnow
from copilot.errors import ValidationFailed


@pytest.fixture
def loaded(app, synthetic_file):
    PracticeImporter(app.knowledge, app.pipeline, app.audit, app.conn).run(CsvPracticeSource(synthetic_file))
    return {p.name: p for p in app.knowledge_repo.list_practices()}


def by_name(wl):
    return {i.practice.name: i for i in wl.items}


def test_worklist_scope_and_reasons(app, loaded):
    wl = app.worklist.build("Saarbrücken")
    names = [i.practice.name for i in wl.items]
    assert set(names) == {"SYNTH Hausarztpraxis Alpha", "SYNTH Kardiologie Beta", "SYNTH Orthopädie Gamma", "SYNTH Neurologie Zeta"}
    alpha = by_name(wl)["SYNTH Hausarztpraxis Alpha"]
    # 5 (Fachrichtung) + 6 (3 Ärzte) – jede Punktvergabe ist begründet
    assert alpha.score == 11 and [r.criterion for r in alpha.reasons] == ["specialty_fit", "practice_size"]
    zeta = by_name(wl)["SYNTH Neurologie Zeta"]
    assert zeta.score == 0 and "Fachrichtung unbekannt" in zeta.unknowns       # fehlende Info -> kein Punkt, sondern "unbekannt"
    assert alpha.next_action == "find_website" or alpha.next_action == "research_website"
    assert names == sorted(names, key=lambda n: (-by_name(wl)[n].score, n.casefold()))


def test_worklist_is_deterministic(app, loaded):
    a = [(i.practice.id, i.score) for i in app.worklist.build("Saarbrücken").items]
    b = [(i.practice.id, i.score) for i in app.worklist.build("saarbruecken").items]
    assert a == b


def test_worklist_region_and_unknown_scope(app, loaded):
    assert len(app.worklist.build("Saarland").items) == 5     # Saarbrücken (4) + Völklingen (1)
    assert [i.practice.name for i in app.worklist.build("Trier").items] == ["SYNTH Hausarztpraxis Epsilon"]
    with pytest.raises(ValidationFailed) as exc:
        app.worklist.build("Berlin")
    assert exc.value.code == "unknown_scope" and "Saarbrücken" in exc.value.message


def test_customers_are_excluded_and_referral_proximity_scored(app, loaded):
    gp, cardio = loaded["SYNTH Hausarztpraxis Alpha"], loaded["SYNTH Kardiologie Beta"]
    app.pipeline.mark_customer(gp.id)
    wl = app.worklist.build("Saarbrücken")
    assert wl.excluded["customer"] == 1 and gp.name not in by_name(wl)
    app.network.derive_for_practice(gp.id)
    derived = by_name(app.worklist.build("Saarbrücken"))[cardio.name]
    ref = next(r for r in derived.reasons if r.criterion == "referral_proximity")
    assert ref.points == 8 and "nicht belegt" in ref.explanation
    # belegt zählt mehr – und nur mit Fact
    fact = app.facts.record_manual(EntityType.PRACTICE, gp.id, FactDraft(key="refers_to_practice", value="belegt"))
    app.network.record_observed(gp.id, cardio.id, fact.id)
    observed = by_name(app.worklist.build("Saarbrücken"))[cardio.name]
    ref = next(r for r in observed.reasons if r.criterion == "referral_proximity")
    assert ref.points == 20 and "belegt" in ref.explanation and "nicht belegt" not in ref.explanation


def test_doctolib_signal_excludes_and_competitor_signal_scores(app, loaded):
    beta, gamma = loaded["SYNTH Kardiologie Beta"], loaded["SYNTH Orthopädie Gamma"]
    app.facts.record_manual(EntityType.PRACTICE, beta.id, FactDraft(key="doctolib_link_present", value=["https://x.invalid"]))
    app.facts.record_manual(EntityType.PRACTICE, gamma.id, FactDraft(key="online_booking_signal", value=["Terminland"]))
    wl = app.worklist.build("Saarbrücken")
    assert wl.excluded["already_doctolib_recognised"] == 1 and beta.name not in by_name(wl)
    g = by_name(wl)[gamma.name]
    assert any(r.criterion == "competitor_booking_signal" and r.fact_ids for r in g.reasons)
    assert g.next_action == "prepare_outreach"


def test_stale_facts_trigger_refresh_and_do_not_score(app, loaded):
    gamma = loaded["SYNTH Orthopädie Gamma"]
    app.facts.record_manual(EntityType.PRACTICE, gamma.id, FactDraft(key="online_booking_signal", value=["Terminland"]))
    wl = app.worklist.build("Saarbrücken", now=utcnow() + timedelta(days=200))
    g = by_name(wl)[gamma.name]
    assert g.next_action == "refresh_research" and not any(r.criterion == "competitor_booking_signal" for r in g.reasons)


def test_save_scores_only_on_prospects_and_limit(app, loaded):
    gp = loaded["SYNTH Hausarztpraxis Alpha"]
    app.pipeline.ensure_prospect(gp.id)
    wl = app.worklist.build("Saarbrücken", limit=1)
    assert len(wl.items) == 1 and wl.items[0].status == "prospect"
    app.pipeline_repo.save_score(gp.id, wl.items[0].score, [{"criterion": "x"}])
    assert app.pipeline_repo.get_prospect(gp.id).score == wl.items[0].score
