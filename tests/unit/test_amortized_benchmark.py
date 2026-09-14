import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('amortized', Path(__file__).resolve().parents[2] / 'scripts/amortized_benchmark.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def arguments(tmp_path, **overrides):
    return SimpleNamespace(**(dict(workspace=tmp_path / 'experiment', output=tmp_path / 'report.json',
                                  execute=False, domain=None, rounds=3, max_calls=6,
                                  timeout=180, model='test-model') | overrides))


def test_offline_matrix_never_claims_tokens_or_calls_provider(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('offline provider call')
    monkeypatch.setattr(bench, 'MeteredCodex', forbidden)
    report = asyncio.run(bench.run(arguments(tmp_path)))
    assert report['provider_attempts'] == 0
    assert len(report['domains']) == 3
    for domain in report['domains'].values():
        assert len(domain['tasks']) == 6
        assert all(row['passed'] for row in domain['tasks'])
        assert [row['memory_hit'] for row in domain['tasks'] if row['arm'] == 'reuse'] == [False, True, True]
        assert all(row['lower_cumulative_tokens_same_acceptance'] is None for row in domain['cumulative'])


@pytest.mark.parametrize('domain', bench.DOMAINS)
def test_acceptance_rejects_prior_artifact_regression(tmp_path, domain):
    root = tmp_path / domain
    bench.seed(root, domain)
    for number in range(1, 4):
        bench.reference(root, domain, number)
        assert bench.validate(root, domain, number)
    target = {'code': 'calculations.py', 'document': 'brief-1.md', 'data': 'analysis.json'}[domain]
    (root / target).write_text('{}')
    assert not bench.validate(root, domain, 3)


def test_real_budget_guard_runs_before_creating_workspace(tmp_path):
    with pytest.raises(SystemExit):
        asyncio.run(bench.run(arguments(tmp_path, execute=True)))
    assert not (tmp_path / 'experiment').exists()


def test_unknown_usage_is_not_zero_and_cumulative_includes_first_task():
    rows = [{'passed': True, 'usage': {'source': 'measured', 'input': 100, 'output': 10, 'cached': 40},
             'wall_seconds': 1},
            {'passed': True, 'usage': {'source': 'measured', 'input': 50, 'output': 5, 'cached': 20},
             'wall_seconds': 2}]
    assert bench.totals(rows)['total_tokens'] == 165
    assert bench.totals(rows)['wall_seconds'] == 3
    rows[0]['usage'] = {'source': 'unavailable'}
    assert bench.totals(rows)['total_tokens'] is None


def test_packet_cwd_is_absolute_for_nested_provider_execution(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    packet = bench.Packet(Path('nested/project'), 'task', None)
    assert packet.working_directory == tmp_path / 'nested/project'
    assert packet.working_directory.is_absolute()


def test_real_failure_stops_without_retry_and_retains_error(tmp_path, monkeypatch):
    class FailedProvider:
        def __init__(self, **kwargs):
            assert kwargs['capabilities'].supports_auto_approval is False
            self.telemetry = {'provider_turns': 0}
        async def execute(self, task, packet):
            assert packet.working_directory.is_absolute()
            return SimpleNamespace(token_usage={'source': 'unavailable'}, status='failed',
                                   error_code='TEST_FAILURE', summary='synthetic failure',
                                   uncertainty_reason='reason', needs_escalation=True)
    monkeypatch.setattr(bench, 'MeteredCodex', FailedProvider)
    report = asyncio.run(bench.run(arguments(tmp_path, execute=True, domain='document')))
    assert report['provider_attempts'] == 2
    assert report['observed_completed_provider_turns'] == 0
    assert report['stopped'] == 'acceptance_failure_no_retry'
    assert all(row['error_code'] == 'TEST_FAILURE' for row in report['domains']['document']['tasks'])
    assert all(row['diagnostic']['summary'] == 'synthetic failure'
               for row in report['domains']['document']['tasks'])


def test_benchmark_provider_uses_explicit_workspace_sandbox(tmp_path, monkeypatch):
    capabilities = bench.CodexCapabilities(available=True, executable='codex',
        supports_noninteractive=True, supports_model_selection=True,
        supports_reasoning_selection=True, supports_structured_output=True,
        supports_working_directory=True, supports_jsonl=True, supports_auto_approval=False)
    captured = {}
    async def communicate(self, args, prompt, working_directory, budget=None):
        captured['args'] = args
        result = {'status': 'completed', 'summary': 'ok', 'files': [], 'findings': [],
                  'confidence': 'high', 'uncertainty_reason': '', 'needs_escalation': False,
                  'learning_evidence': []}
        import json
        events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(result)}},
                  {'type': 'turn.completed', 'usage': {'input_tokens': 1, 'output_tokens': 1,
                                                       'cached_input_tokens': 0}}]
        return 0, '\n'.join(json.dumps(item) for item in events).encode(), b''
    monkeypatch.setattr(bench.MeteredCodex, '_communicate', communicate)
    provider = bench.MeteredCodex(capabilities=capabilities)
    root = tmp_path.resolve()
    task = bench.Task('t', 'r', 'test', 'owner', ['text'], kind=bench.TaskKind.AGENT,
                      metadata={'working_directory': str(root), 'read_only': False})
    receipt = asyncio.run(provider.execute(task, packet=bench.Packet(root, 'test', None)))
    assert receipt.status == 'completed'
    assert '--sandbox' in captured['args'] and 'workspace-write' in captured['args']
    assert '--approve-for-me' not in captured['args']
