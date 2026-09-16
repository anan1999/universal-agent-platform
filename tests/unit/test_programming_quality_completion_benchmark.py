from scripts import programming_quality_completion_benchmark as benchmark


def test_programming_quality_runner_is_pinned_to_sol():
    assert benchmark.MODEL == "gpt-5.6-sol"


def test_programming_quality_runner_has_five_cumulative_contracts():
    assert len(benchmark.programming.TASKS) == 5
    assert set(benchmark.programming.QUALITY_CONTRACTS) == {1, 2, 3, 4, 5}
    assert "FastAPI" in benchmark.programming.TASKS[0]
    assert "/reports/monthly/{month}" in benchmark.programming.TASKS[3]
