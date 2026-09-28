import pytest

from copilot.errors import IntegrityViolation, NotFound, ValidationFailed
from tests.test_scanner import by_name, loaded, n, scan  # noqa: F401  (Fixture 'loaded' wiederverwendet)


@pytest.fixture
def queued(app, loaded, scan_source):
    scan(app, scope="Saarbrücken", from_files=[scan_source])
    return {m.record.name + "|" + (m.record.street or ""): m for m in app.merge_repo.list("open")}


def test_same_decision_attaches_and_is_remembered(app, loaded, scan_source, queued):
    entry = queued["SYNTH MVZ Nachfolge|Probeallee 3"]
    before = n(app, "k_practice")
    result = app.merge.resolve(entry.id, "same")
    assert result.decision == "same" and result.practice_id == loaded["SYNTH Orthopädie Gamma"].id
    assert n(app, "k_practice") == before                                      # nichts Neues, nur angehängt
    assert app.merge_repo.get(entry.id).status == "same"
    # gleiche Schreibweise wird künftig eindeutig zugeordnet, nicht erneut eingereiht
    again = scan(app, scope="Saarbrücken", from_files=[scan_source]).ingest[0][1]
    assert again.queued == 0 and again.already_queued == 1                     # nur der andere offene Eintrag
    assert n(app, "k_practice") == before


def test_different_decision_creates_practice_once(app, loaded, scan_source, queued):
    entry = queued["SYNTH Orthopädie Gamma|Andere Str. 9"]
    before = n(app, "k_practice")
    result = app.merge.resolve(entry.id, "different")
    assert result.created and n(app, "k_practice") == before + 1
    again = scan(app, scope="Saarbrücken", from_files=[scan_source]).ingest[0][1]
    assert n(app, "k_practice") == before + 1 and again.queued == 0            # jetzt eindeutig bekannt


def test_decisions_are_final_and_validated(app, queued):
    entry = next(iter(queued.values()))
    app.merge.resolve(entry.id, "same")
    with pytest.raises(IntegrityViolation):
        app.merge.resolve(entry.id, "different")
    with pytest.raises(ValidationFailed):
        app.merge.resolve(next(m.id for m in app.merge_repo.list("open")), "maybe")
    with pytest.raises(NotFound):
        app.merge.resolve(9999, "same")


def test_merge_audit_has_no_pii(app, queued):
    app.merge.resolve(next(iter(queued.values())).id, "different")
    event = app.audit.tail(1)[0]
    assert event["event_type"] == "merge.resolve" and "SYNTH" not in event["details"]


def test_merge_queue_never_changes_practices_on_its_own(app, loaded, scan_source):
    snapshot = [(p.id, p.name, p.street, p.website_url) for p in app.knowledge_repo.list_practices()]
    scan(app, scope="Saarbrücken", from_files=[scan_source])
    after = {(p.id, p.name, p.street, p.website_url) for p in app.knowledge_repo.list_practices()}
    # bestehende Praxen: nur Lücken gefüllt (Beta bekommt nichts überschrieben), Namen/Adressen unverändert
    assert all(row in after for row in snapshot)
