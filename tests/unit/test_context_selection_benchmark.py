import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('selection', Path(__file__).resolve().parents[2] / 'scripts/context_selection_benchmark.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def args(tmp_path, **changes):
    return SimpleNamespace(**(dict(execute=True, workspace=tmp_path/'work', output=tmp_path/'result.json',
                                  model='model', timeout=120, rounds=2, max_calls=4) | changes))


def test_catalog_expected_and_selection_are_exact():
    assert len(bench.CATALOG) > 10000
    assert bench.record(17) in bench.CATALOG and bench.record(83) in bench.CATALOG
    assert bench.expected(17) == 'RULE-017|legal|apac|31|1119|Q2'
    assert len(bench.ROUND_KEYS) == 6 and len(set(bench.ROUND_KEYS)) == 6


def test_budget_and_overwrite_guards_precede_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(bench, 'MeteredCodex', lambda **kwargs: (_ for _ in ()).throw(AssertionError()))
    with pytest.raises(SystemExit):
        asyncio.run(bench.run(args(tmp_path, max_calls=5)))
    assert not (tmp_path/'work').exists()
    (tmp_path/'result.json').write_text('existing')
    with pytest.raises(SystemExit):
        asyncio.run(bench.run(args(tmp_path)))


def test_two_round_cumulative_includes_equal_first_cost_and_selected_second(tmp_path, monkeypatch):
    class Provider:
        calls = 0
        def __init__(self, **kwargs):
            self.telemetry = {'tool_calls': 0}
        async def execute(self, task, packet):
            Provider.calls += 1
            number = int(task.title.rsplit('-', 1)[1])
            # Model stub resolves from inline data; measured usage reflects packet size.
            summary = bench.expected(number)
            usage = {'source': 'measured', 'input': len(packet.text), 'output': len(summary), 'cached': 0}
            return SimpleNamespace(status='completed', summary=summary, error_code=None, token_usage=usage)
    monkeypatch.setattr(bench, 'MeteredCodex', Provider)
    report = asyncio.run(bench.run(args(tmp_path)))
    assert Provider.calls == 4
    assert [row['context_kind'] for row in report['tasks']] == ['full', 'full', 'selected', 'full']
    assert report['cumulative'][0]['lower_tokens_same_acceptance'] is False
    assert report['cumulative'][1]['lower_tokens_same_acceptance'] is True
    assert report['conclusion'] == 'YES'


def test_unknown_usage_cannot_become_savings():
    rows = [{'passed': True, 'usage': {'source': 'unavailable'}, 'wall_seconds': 1}]
    assert bench.totals(rows)['total_tokens'] is None


def test_six_round_budget_and_alternating_order(tmp_path, monkeypatch):
    class Provider:
        calls = 0
        def __init__(self, **kwargs):
            self.telemetry = {'tool_calls': 0}
        async def execute(self, task, packet):
            Provider.calls += 1
            number = int(task.title.rsplit('-', 1)[1])
            summary = bench.expected(number)
            return SimpleNamespace(status='completed', summary=summary, error_code=None,
                                   token_usage={'source': 'measured', 'input': len(packet.text),
                                                'output': len(summary), 'cached': 0})
    monkeypatch.setattr(bench, 'MeteredCodex', Provider)
    report = asyncio.run(bench.run(args(tmp_path, rounds=6, max_calls=12)))
    assert Provider.calls == 12
    assert len(report['cumulative']) == 6
    assert [row['order'] for row in report['tasks'][::2]] == [
        ['cold', 'selected'], ['selected', 'cold'], ['cold', 'selected'],
        ['selected', 'cold'], ['cold', 'selected'], ['selected', 'cold']]
    assert [row['context_kind'] for row in report['tasks'] if row['arm'] == 'selected'] == [
        'full', 'selected', 'selected', 'selected', 'selected', 'selected']
    assert report['conclusion'] == 'YES'
