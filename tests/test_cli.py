import json
from pathlib import Path

from manufacturing_monitor import cli
from manufacturing_monitor.workflow import build_monitor_result


FIXTURE = Path(__file__).parent / "fixtures" / "fred-ipman-sample.json"


def test_project_info_does_not_contact_fred(monkeypatch, capsys):
    cli.main(["--project-info"])

    assert "Network: not contacted" in capsys.readouterr().out


def test_cli_runs_with_mocked_external_behavior(monkeypatch, tmp_path, capsys):
    fixture_data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = build_monitor_result(fixture_data)
    raw_path = tmp_path / "raw" / "ipman.json"
    processed_path = tmp_path / "processed" / "ipman.json"

    monkeypatch.setenv("FRED_API_KEY", "test-key")
    monkeypatch.setattr(cli, "RAW_OUTPUT_PATH", raw_path)
    monkeypatch.setattr(cli, "PROCESSED_OUTPUT_PATH", processed_path)
    monkeypatch.setattr(cli, "run_monitor", lambda _request: result)

    cli.main([])

    output = capsys.readouterr().out
    assert "Latest manufacturing index: 103.1189 on 2026-05-01" in output
    assert json.loads(raw_path.read_text(encoding="utf-8"))["count"] == 6
    assert json.loads(processed_path.read_text(encoding="utf-8"))[-1]["value"] == "."
