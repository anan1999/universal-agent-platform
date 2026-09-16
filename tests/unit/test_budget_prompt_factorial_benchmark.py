from scripts import budget_prompt_factorial_benchmark as benchmark


def result(tokens, *, outcome="contract_passed", complete=True):
    return {
        "observed_tokens": tokens, "cached_input": 10, "output_tokens": 2,
        "provider_tool_calls": 3, "provider_messages": 2, "attempts": 1,
        "outcome": outcome, "measurement_complete": complete,
    }


def test_factorial_changes_only_cap_and_batching_prompt():
    assert benchmark.MODEL == "gpt-5.6-sol"
    assert benchmark.ARMS == {
        "cap8_plain": {"cap": 8, "batching": False},
        "cap6_plain": {"cap": 6, "batching": False},
        "cap8_batch": {"cap": 8, "batching": True},
        "cap6_batch": {"cap": 6, "batching": True},
    }
    assert len(benchmark.ORDERS) == 4
    assert all(set(order) == set(benchmark.ARMS) for order in benchmark.ORDERS)


def test_summary_reports_orthogonal_main_effects():
    block = {"arms": {
        "cap8_plain": result(100), "cap6_plain": result(90),
        "cap8_batch": result(80), "cap6_batch": result(70),
    }}
    summary = benchmark.summarize([block])
    assert summary["main_effects"]["cap6_minus_cap8_tokens"] == -20
    assert summary["main_effects"]["batch_minus_plain_tokens"] == -40
    assert summary["all_contracts_passed"]
    assert summary["all_measurements_complete"]


def test_combined_goal_uses_all_five_frozen_contract_stages():
    assert len(benchmark.programming.TASKS) == 5
    assert "/exports/expenses.csv" in benchmark.GOAL
    assert "/reports/monthly/{month}" in benchmark.GOAL
    assert "dashboard month input" in benchmark.GOAL
