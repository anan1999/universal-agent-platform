import json
import sqlite3
import sys

import pytest
import yaml

from adaptive_agent.core.tools import ToolResult
from adaptive_agent.project.direct import main, prepare
from adaptive_agent.project.experience import OperationExperience, TTL


def configure(root):
    (root / '.agent').mkdir(exist_ok=True)
    (root / '.agent/commands.yaml').write_text(yaml.safe_dump({'commands': {
        'test': {'command': [sys.executable, '-c', 'assert 2 + 2 == 4']}}}))


@pytest.mark.parametrize('artifact', ['app.py', 'package.json', 'report.md', 'research.csv', 'brand.txt', 'lighting.yaml'])
def test_cross_task_procedure_reuse_domain_matrix(tmp_path, monkeypatch, capsys, artifact):
    configure(tmp_path)
    (tmp_path / artifact).write_text('{}')
    monkeypatch.chdir(tmp_path)
    assert OperationExperience(tmp_path).reusable() == []
    for task_number in range(3):
        assert main(['check', 'project_test', '--experience']) == 0
        output = json.loads(capsys.readouterr().out)
        assert output['procedures_saved'] == ['project_test']
        # New object, as in a fresh task/process; real allowlisted subprocess ran.
        result = prepare(tmp_path, 'Check the project deliverable', use_experience=True)
        assert result['provider_calls'] == 0
        assert 'verified_procedures' not in result['context']
        assert result['context']['commands_to_verify'] == {
            'test': str([sys.executable, '-c', 'assert 2 + 2 == 4'])}
        assert result['validation_memory']['applied'] is True
        assert result['validation_memory']['successful_runs']['project_test'] == task_number + 1
    # This tests reusable mechanics, not the quality of any particular domain.


def test_failure_config_environment_and_ttl_revoke(tmp_path, monkeypatch):
    configure(tmp_path)
    store = OperationExperience(tmp_path)
    ok = ToolResult('project_test', 'completed', 'ok', exit_code=0)
    assert store.record(ok, store.fingerprint())
    assert store.reusable()
    with monkeypatch.context() as context:
        context.setenv('VIRTUAL_ENV', 'different')
        assert not store.reusable()
    (tmp_path / 'package.json').write_text('{}')
    assert not store.reusable()
    assert store.record(ok, store.fingerprint())
    assert not store.record(ToolResult('project_test', 'failed', 'failed'), store.fingerprint())
    assert not store.reusable()
    assert store.record(ok, store.fingerprint())
    with sqlite3.connect(store.path) as db:
        db.execute('UPDATE operations SET verified=verified-?', (TTL + 1,))
    assert not store.reusable()


def test_success_memory_silently_filters_multiple_validation_candidates(tmp_path):
    (tmp_path / '.agent').mkdir()
    (tmp_path / '.agent/commands.yaml').write_text(yaml.safe_dump({'commands': {
        'test': {'command': [sys.executable, '-c', 'assert True']},
        'build': {'command': [sys.executable, '-c', 'print("build")']},
    }}), encoding='utf-8')
    cold = prepare(tmp_path, 'Validate the change')['context']['commands_to_verify']
    store = OperationExperience(tmp_path)
    assert store.record(
        ToolResult('project_test', 'completed', 'ok', exit_code=0), store.fingerprint())
    warm = prepare(tmp_path, 'Validate the change', use_experience=True)
    assert set(cold) == {'test', 'build'}
    assert set(warm['context']['commands_to_verify']) == {'test'}
    assert warm['validation_memory']['selected_commands'] == ['test']


def test_no_unobserved_success_or_changed_during_execution(tmp_path):
    configure(tmp_path)
    store = OperationExperience(tmp_path)
    assert not store.record(ToolResult('project_test', 'completed', 'claimed'), store.fingerprint())
    before = store.fingerprint()
    (tmp_path / 'config.yaml').write_text('changed: true')
    assert not store.record(ToolResult('project_test', 'completed', 'ok', exit_code=0), before)
    assert not store.reusable()


def test_corruption_is_optional_and_no_logs_saved(tmp_path):
    configure(tmp_path)
    store = OperationExperience(tmp_path)
    assert store.record(ToolResult('project_test', 'completed', 'SECRET', 'SECRET', exit_code=0), store.fingerprint())
    assert b'SECRET' not in store.path.read_bytes()
    store.path.write_bytes(b'broken')
    assert not store.reusable()
    assert not store.record(ToolResult('project_test', 'completed', 'ok', exit_code=0), store.fingerprint())


def test_default_has_zero_operation_memory_access_even_when_memory_exists(tmp_path, monkeypatch, capsys):
    configure(tmp_path)
    store = OperationExperience(tmp_path)
    assert store.record(ToolResult('project_test', 'completed', 'ok', exit_code=0), store.fingerprint())
    before = store.path.read_bytes()
    def forbidden(*args, **kwargs):
        raise AssertionError('default must not access operation memory')
    monkeypatch.setattr(OperationExperience, '__init__', forbidden)
    monkeypatch.chdir(tmp_path)
    for _ in range(3):
        assert main(['check', 'project_test']) == 0
        assert 'procedures_saved' not in json.loads(capsys.readouterr().out)
        assert main(['prepare', 'Check deliverable', '--json']) == 0
        result = json.loads(capsys.readouterr().out)
        assert 'verified_procedures' not in result['context']
        assert 'verified_procedures' not in result['instruction']
        assert result['validation_memory']['enabled'] is False
    assert before == store.path.read_bytes()


def test_separate_checks_do_not_hide_earlier_failure(tmp_path, monkeypatch, capsys):
    configure(tmp_path)
    path = tmp_path / '.agent/commands.yaml'
    path.write_text(yaml.safe_dump({'commands': {
        'test': {'command': [sys.executable, '-c', 'import sys; print("failure evidence"); sys.exit(7)']},
        'build': {'command': [sys.executable, '-c', 'print("ok")']}}}))
    monkeypatch.chdir(tmp_path)
    assert main(['check', 'project_test', 'project_build']) == 1
    result = json.loads(capsys.readouterr().out)
    assert [item['exit_code'] for item in result['checks']] == [7, 0]
    assert [item['status'] for item in result['checks']] == ['failed', 'completed']
    assert 'failure evidence' in result['checks'][0]['output']
    assert not (tmp_path / '.agent/cache/operations.sqlite3').exists()


def test_fresh_cli_process_preserves_failure(tmp_path):
    import os
    import subprocess
    from pathlib import Path
    configure(tmp_path)
    (tmp_path / '.agent/commands.yaml').write_text(yaml.safe_dump({'commands': {
        'test': {'command': [sys.executable, '-c', 'import sys; sys.exit(9)']},
        'build': {'command': [sys.executable, '-c', 'pass']}}}))
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[2] / 'src')
    result = subprocess.run([sys.executable, '-m', 'adaptive_agent.cli', 'check',
                             'project_test', 'project_build'], cwd=tmp_path,
                            env=environment, capture_output=True, text=True, timeout=30)
    assert result.returncode == 1
    checks = json.loads(result.stdout)['checks']
    assert [item['exit_code'] for item in checks] == [9, 0]
    assert not (tmp_path / '.agent/cache/operations.sqlite3').exists()
