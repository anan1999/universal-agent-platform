import json
from pathlib import Path

from adaptive_agent.cli import main
from adaptive_agent.project.direct import prepare


def test_cross_task_note_invalidates_and_does_not_open_platform_db(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'app').mkdir()
    source = tmp_path / 'app' / 'main.py'
    source.write_text('date_field = "date"')
    import adaptive_agent.cli as cli
    monkeypatch.setattr(cli, 'database', lambda: (_ for _ in ()).throw(AssertionError('DB opened')))
    assert main(['remember', 'app/main.py', 'Expense dates use the date field.']) == 0
    capsys.readouterr()
    assert main(['prepare', 'Modify backend API', '--json']) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['provider_calls'] == 0
    assert result['context']['notes'][0]['summary'] == 'Expense dates use the date field.'
    source.write_text('date_field = "created_at"')
    assert prepare(tmp_path, 'Modify backend API')['context']['notes'] == []


def test_check_reports_missing_allowlist_as_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(['check', 'project_test']) == 1
    assert json.loads(capsys.readouterr().out)['checks'][0]['status'] == 'skipped'


def test_remember_rejects_outside_source(tmp_path, monkeypatch):
    import pytest
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        main(['remember', '../outside', 'note'])
