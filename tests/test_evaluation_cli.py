"""CLI reports remain available even when a regression fails."""

import json

import pytest

from relayops.cli import main


@pytest.mark.parametrize("passed,expected_exit", [(8, None), (7, 1)])
def test_cli_exports_the_report_and_preserves_failure_exit(tmp_path, monkeypatch, capsys, passed, expected_exit):
    import relayops.evaluation
    result = {"total": 8, "passed": passed, "results": [{"title": "Décimales", "passed": False}]}
    monkeypatch.setattr(relayops.evaluation, "evaluate", lambda: result)
    monkeypatch.setenv("RELAYOPS_ENV", "local")
    destination = tmp_path / "nested" / "evidence.json"
    monkeypatch.setattr("sys.argv", ["relayops", "--evaluate", "--report", str(destination)])
    if expected_exit:
        with pytest.raises(SystemExit) as error:
            main()
        assert error.value.code == expected_exit
    else:
        main()
    assert json.loads(destination.read_text(encoding="utf-8")) == result
    assert json.loads(capsys.readouterr().out) == result


def test_cli_rejects_report_flag_without_evaluation(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    monkeypatch.setattr("sys.argv", ["relayops", "--report", str(destination)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert not destination.exists()
