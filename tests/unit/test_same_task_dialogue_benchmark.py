import pytest

from scripts.same_task_dialogue_benchmark import usage_delta


def test_usage_delta_accounts_for_cached_tokens_without_double_counting():
    previous = {"input_tokens": 100, "cached_input_tokens": 40,
                "output_tokens": 20}
    current = {"input_tokens": 350, "cached_input_tokens": 210,
               "output_tokens": 65}
    assert usage_delta(previous, current) == {
        "input_tokens": 250, "cached_input_tokens": 170,
        "output_tokens": 45, "total_tokens": 295, "uncached_tokens": 125}


def test_usage_delta_rejects_missing_or_nonmonotonic_reports():
    previous = {"input_tokens": 100, "cached_input_tokens": 40,
                "output_tokens": 20}
    with pytest.raises(ValueError):
        usage_delta(previous, {})
    with pytest.raises(ValueError):
        usage_delta(previous, {"input_tokens": 99, "cached_input_tokens": 40,
                               "output_tokens": 20})
