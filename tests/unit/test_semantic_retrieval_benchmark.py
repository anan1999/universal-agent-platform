import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

spec = importlib.util.spec_from_file_location('semantic', Path(__file__).resolve().parents[2] / 'scripts/semantic_retrieval_benchmark.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


def arguments(tmp_path, **changes):
    return SimpleNamespace(**(dict(execute=True, workspace=tmp_path/'work', output=tmp_path/'result.json',
                                  model='model', timeout=120, max_calls=6) | changes))


@pytest.mark.parametrize('case', bench.CASES)
def test_answer_blind_selector_finds_all_required_evidence(case):
    context, evidence = bench.select(case['question'])
    assert len(context) < len(bench.CORPUS) / 4
    assert all(marker in context for marker in case['markers'])
    assert 2 <= len(evidence) <= 4
    assert all(item['score'] > 0 and item['matched_terms'] for item in evidence)


def test_corpus_is_nontrivial_and_questions_hide_internal_ids():
    assert len(bench.CORPUS) > 12000 and len(bench.CHUNKS) == 96
    for case in bench.CASES:
        assert not any(marker in case['question'] for marker in case['markers'])
        assert case['expected'] not in case['question']
        assert case['format']


def test_budget_guard_precedes_workspace_creation(tmp_path):
    with pytest.raises(SystemExit):
        asyncio.run(bench.run(arguments(tmp_path, max_calls=7)))
    assert not (tmp_path/'work').exists()


def test_three_round_stub_preserves_quality_and_reduces_context(tmp_path, monkeypatch):
    class Provider:
        calls = 0
        def __init__(self, **kwargs):
            self.telemetry = {'tool_calls': 0, 'assistant_messages': 1}
        async def execute(self, task, packet):
            Provider.calls += 1
            case = next(case for case in bench.CASES if case['question'] == task.title)
            return SimpleNamespace(status='completed', summary=case['expected'], error_code=None,
                token_usage={'source': 'measured', 'input': len(packet.text),
                             'output': len(case['expected']), 'cached': 0})
    monkeypatch.setattr(bench, 'MeteredCodex', Provider)
    report = asyncio.run(bench.run(arguments(tmp_path)))
    assert Provider.calls == 6 and report['conclusion'] == 'YES'
    assert all(row['passed'] for row in report['tasks'])
    assert [row['context_kind'] for row in report['tasks'] if row['arm'] == 'retrieved'] == [
        'full', 'retrieved', 'retrieved']
    assert report['cumulative'][0]['lower_tokens_same_acceptance'] is False
    assert report['cumulative'][-1]['lower_tokens_same_acceptance'] is True
    assert all(row['observed_answer'] for row in report['tasks'])


def test_unavailable_usage_is_not_zero():
    assert bench.aggregate([{'passed': True, 'usage': {'source': 'unavailable'}, 'seconds': 1}])['total_tokens'] is None
