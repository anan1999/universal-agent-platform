import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('direct_bench', ROOT / 'scripts/direct_benchmark.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_pair_preserves_goal_and_executor_only_adds_support_context(tmp_path):
    baseline = benchmark.Packet(tmp_path, benchmark.GOAL)
    supported = benchmark.Packet(tmp_path, benchmark.GOAL, {'context': {'paths': ['app/']}})
    assert supported.render().startswith(baseline.render())
    assert baseline.read_only is supported.read_only is False
    assert baseline.working_directory == supported.working_directory
    assert '"month":"YYYY-MM"' in baseline.render()
    assert '"categories"' in baseline.render()


def test_observable_counts_do_not_claim_internal_reasoning(monkeypatch):
    import asyncio
    import json
    from adaptive_agent.providers.codex.provider import CodexCapabilities, CodexProvider

    async def communicate(self, *args, **kwargs):
        events = [
            {'type': 'item.started', 'item': {'type': 'command_execution'}},
            {'type': 'item.completed', 'item': {'type': 'command_execution'}},
            {'type': 'item.completed', 'item': {'type': 'agent_message', 'text': 'done'}},
            {'type': 'turn.completed'},
        ]
        return 0, '\n'.join(map(json.dumps, events)).encode(), b''
    monkeypatch.setattr(CodexProvider, '_communicate', communicate)
    provider = benchmark.MeteredCodex(capabilities=CodexCapabilities())
    asyncio.run(provider._communicate([], '', Path('.')))
    assert provider.telemetry['tool_calls'] == 1
    assert provider.telemetry['assistant_message_chars'] == 4
    assert provider.telemetry['internal_reasoning_rounds'] is None


def test_action_trace_is_private_and_marks_only_observable_repetition():
    import json
    command = 'Get-Content app/main.py; pytest -q # SECRET_VALUE'
    item = {'type': 'command_execution', 'command': command,
            'aggregated_output': 'SECRET_VALUE ModuleNotFoundError', 'exit_code': 1}
    trace = benchmark.action_trace([
        {'type': 'item.started', 'item': item},
        {'type': 'item.completed', 'item': item},
        {'type': 'item.completed', 'item': item},
        {'type': 'item.completed', 'item': {'type': 'file_change'}},
    ])
    assert len(trace) == 3
    assert trace[0]['labels'] == ['inspection', 'validation']
    assert trace[0]['fixture_paths_mentioned'] == ['app/main.py']
    assert trace[0]['failure_hints'] == ['missing_dependency']
    assert trace[0]['exit_code'] == 1
    assert trace[0]['repeated_exact_command'] is False
    assert trace[1]['repeated_exact_command'] is True
    assert trace[2]['labels'] == ['editing']
    assert 'SECRET_VALUE' not in json.dumps(trace)
    assert command not in json.dumps(trace)


def test_procedure_pair_only_adds_observed_evidence(tmp_path, monkeypatch):
    import shutil
    from adaptive_agent.core.tools import ToolExecutor, ToolResult
    roots = {name: tmp_path / name for name in ('baseline', 'uap')}
    for root in roots.values():
        shutil.copytree(benchmark.FIXTURE, root, ignore=shutil.ignore_patterns('__pycache__'))
    monkeypatch.setattr(ToolExecutor, 'run', lambda self, tool:
                        ToolResult(tool, 'completed', 'ok', exit_code=0))
    contexts, training = benchmark.prepare_reuse_pair(roots)
    cold = contexts['baseline']['context']
    warm = dict(contexts['uap']['context'])
    assert warm.pop('verified_procedures')[0]['successful_runs'] == 1
    assert cold == warm
    assert not training['baseline']['evidence_saved']
    assert training['uap']['evidence_saved']
