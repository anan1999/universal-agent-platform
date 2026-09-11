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
