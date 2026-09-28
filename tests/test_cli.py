from pathlib import Path

import pytest

from copilot.cli.main import main

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_HOME", str(REPO))
    monkeypatch.setenv("COPILOT_CONFIG_DIR", str(REPO / "config"))
    monkeypatch.setenv("COPILOT_DATA_DIR", str(tmp_path / "data"))
    return tmp_path


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_end_to_end(env, capsys, synthetic_file):
    assert run(capsys, "init")[0] == 0
    code, out, _ = run(capsys, "import", "practices", str(synthetic_file), "--dry-run")
    assert code == 0 and "[DRY-RUN]" in out and "neu: 7" in out
    assert "0 Praxen" in run(capsys, "practice", "list")[1]
    code, out, _ = run(capsys, "import", "practices", str(synthetic_file))
    assert code == 0 and "Zeile 9: missing_name" in out and "Zeile 10: invalid_plz" in out
    code, out, _ = run(capsys, "worklist", "Saarbrücken")
    assert code == 0 and "Arbeitsliste: Saarbrücken (4 Praxen)" in out and "nächste Aktion" in out
    code, out, _ = run(capsys, "practice", "show", "1")
    assert "Unbekannt / zu klären" in out and "Belegte Fakten (aktuell): keine" in out
    assert run(capsys, "network", "derive", "--practice", "1")[0] == 0
    code, out, _ = run(capsys, "network", "list", "--practice", "1")
    assert "ABGELEITET" in out and "BEOBACHTET" not in out
    assert "import.practices" in run(capsys, "audit")[1]


def test_errors_are_structured_and_have_exit_codes(env, capsys):
    code, _, err = run(capsys, "practice", "show", "999")
    assert code == 4 and "practice_not_found" in err
    code, _, err = run(capsys, "worklist", "Berlin")
    assert code == 3 and "unknown_scope" in err
    code, _, err = run(capsys, "import", "practices", "/nicht/vorhanden.csv")
    assert code == 8 and "file_not_found" in err
    code, _, err = run(capsys, "network", "observe", "--from", "1", "--to", "2", "--fact", "1")
    assert code == 4 and "fact_not_found" in err


def test_research_blocked_by_default_policy(env, capsys, synthetic_file):
    run(capsys, "import", "practices", str(synthetic_file))
    code, _, err = run(capsys, "research", "website", "--practice", "4")   # Website: synth-delta.invalid, nicht freigegeben
    assert code == 6 and "domain_not_allowed" in err
    code, _, err = run(capsys, "research", "website", "--practice", "1", "--url", "https://www.doctolib.de/x")
    assert code == 6 and "hard_blocked_domain" in err


def test_manual_fact_and_observed_relationship(env, capsys, synthetic_file):
    run(capsys, "import", "practices", str(synthetic_file))
    code, out, _ = run(capsys, "fact", "add", "--practice", "1", "--key", "refers_to_practice", "--value", '"belegt"', "--note", "Gespräch")
    assert code == 0 and "BELEGT" in out
    code, out, _ = run(capsys, "network", "observe", "--from", "1", "--to", "2", "--fact", "1")
    assert code == 0 and "BEOBACHTET" in out


def test_no_command_has_external_effects():
    from copilot.cli.main import build_parser
    text = build_parser().format_help().lower()
    for forbidden in ("send", "mail", "linkedin", "crm", "post"):
        assert forbidden not in text.replace("(level 1/2: research & vorschläge)", "")
