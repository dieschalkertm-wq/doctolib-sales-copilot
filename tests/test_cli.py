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
    assert code == 6 and "doctolib_not_cleared" in err


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


# ---------------------------------------------------------------- Territory Scanner
@pytest.fixture
def scan_env(env, capsys, synthetic_file):
    run(capsys, "import", "practices", str(synthetic_file))
    return env


def test_territory_without_subcommand_still_shows_territory(env, capsys):
    for argv in (("territory",), ("territory", "show")):
        code, out, _ = run(capsys, *argv)
        assert code == 0 and "Saarland (saarland): Saarbrücken" in out


def test_scan_place_radius_and_specialty(scan_env, capsys, scan_source):
    code, out, _ = run(capsys, "territory", "scan", "saarbrücken")
    assert code == 0 and "Territory Scan: Saarbrücken" in out and "Zuordnung nach Ortsangabe" in out
    code, out, _ = run(capsys, "territory", "scan", "saarbrücken", "--radius", "10")
    assert "10 km um Saarbrücken" in out and "möglicherweise im Radius" in out and "Genauigkeit:" in out
    code, out, _ = run(capsys, "territory", "scan", "saarbrücken", "--specialty", "orthopaedie")
    assert "SYNTH Orthopädie Gamma" in out and "SYNTH Kardiologie Beta" not in out


def test_scan_from_file_dry_run_then_real(scan_env, capsys, scan_source):
    code, out, _ = run(capsys, "territory", "scan", "Saarbrücken", "--from-file", str(scan_source), "--dry-run")
    assert code == 0 and "[DRY-RUN" in out and "neu 3" in out and "außerhalb Gebiet 2" in out and "Merge-Queue 2" in out and "#(neu)" in out
    assert "0 offene Einträge" in run(capsys, "merge", "list")[1]                    # Dry-Run hat nichts eingereiht
    code, out, _ = run(capsys, "territory", "scan", "Saarbrücken", "--from-file", str(scan_source))
    assert "Mögliche Dubletten" in out and "nichts wurde zusammengeführt" in out
    code, out, _ = run(capsys, "merge", "list")
    assert "2 offene Einträge" in out and "Confidence" in out
    code, out, _ = run(capsys, "merge", "resolve", "1", "--same")
    assert code == 0 and "angehängt" in out
    assert run(capsys, "merge", "resolve", "1", "--different")[0] == 5               # bereits entschieden
    assert run(capsys, "merge", "resolve", "2")[0] == 3                              # genau eine Option verlangt


def test_scan_json_output(scan_env, capsys):
    import json
    code, out, _ = run(capsys, "territory", "scan", "Saarbrücken", "--json", "--limit", "2")
    data = json.loads(out)
    assert code == 0 and len(data["items"]) == 2 and data["area"]["accuracy"]


def test_scan_errors_have_structured_codes(scan_env, capsys):
    cases = [(("territory", "scan"), 3, "scope_required"),
             (("territory", "scan", "Berlin"), 3, "unknown_scope"),
             (("territory", "scan", "Saarbrücken", "--specialty", "zauber"), 3, "unknown_specialty"),
             (("territory", "scan", "Saarland", "--radius", "5"), 3, "radius_needs_place"),
             (("territory", "scan", "Saarbrücken", "--provider", "doctolib"), 6, "provider_disabled"),
             (("territory", "scan", "Saarbrücken", "--provider", "google"), 3, "unknown_provider"),
             (("territory", "scan", "Saarbrücken", "--from-file", "/nicht/da.csv"), 8, "file_not_found"),
             (("territory", "scan", "--around-customers", "Saarbrücken"), 3, "no_customer_anchors")]
    for argv, exit_code, code in cases:
        got, _, err = run(capsys, *argv)
        assert (got, code in err) == (exit_code, True), (argv, err)


def test_scan_research_flag_respects_default_deny(scan_env, capsys):
    code, out, _ = run(capsys, "territory", "scan", "Saarbrücken", "--research")
    assert code == 0 and "blockiert (domain_not_allowed)" in out                     # kein Abruf ohne Domain-Freigabe


def test_providers_overview_separates_working_from_prepared(env, capsys):
    code, out, _ = run(capsys, "providers")
    rows = {line.split()[1]: line.split()[2] for line in out.strip().splitlines()}
    assert code == 0
    assert rows == {"local_import": "ready", "practice_website": "ready", "map": "disabled",
                    "doctolib": "disabled", "llm_gateway": "disabled"}
    assert "KEINE Domain freigegeben" in out
