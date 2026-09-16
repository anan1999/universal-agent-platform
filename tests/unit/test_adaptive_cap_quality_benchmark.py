import inspect

from scripts import adaptive_cap_quality_benchmark as benchmark


def arm(tokens, attempts=1):
    return {"observed_tokens": tokens, "cached_input": 10, "output_tokens": 2,
            "provider_tool_calls": 3, "provider_messages": 2, "attempts": attempts,
            "outcome": "contract_passed", "measurement_complete": True}


def test_pilot_is_pinned_to_sol_and_only_changes_cap():
    assert benchmark.MODEL == "gpt-5.6-sol"
    assert benchmark.ARMS == {"normal_8": 8, "reduced_6": 6}
    source = inspect.getsource(benchmark.CapPacket)
    assert "Hard envelope" in source
    assert "provider tool calls" in source


def test_summary_counts_total_cost_quality_and_pair_direction():
    rows = [
        {"arms": {"normal_8": arm(100), "reduced_6": arm(80)}},
        {"arms": {"normal_8": arm(100), "reduced_6": arm(120, 2)}},
    ]
    result = benchmark.summarize(rows)
    assert result["normal_8"]["observed_tokens"] == 200
    assert result["reduced_6"]["observed_tokens"] == 200
    assert result["reduced_6"]["attempts"] == 3
    assert result["reduced_percent_delta"] == 0
    assert result["pair_wins"] == {
        "normal_8": 1, "reduced_6": 1, "ties": 0, "excluded": 0}
    assert result["all_contracts_passed"]


def test_summary_excludes_incomplete_measurements_from_wins():
    incomplete = arm(0)
    incomplete.update(outcome="measurement_incomplete", measurement_complete=False)
    result = benchmark.summarize([
        {"arms": {"normal_8": arm(100), "reduced_6": incomplete}},
    ])
    assert result["pair_wins"] == {
        "normal_8": 0, "reduced_6": 0, "ties": 0, "excluded": 1}


def test_live_usage_flag_is_task_metadata_not_budget_metadata():
    source = inspect.getsource(benchmark.execute)
    assert 'current.metadata["codex_live_usage"] = True' in source
    assert '"codex_live_usage": True' not in source


def test_runner_can_reuse_all_legacy_context_cache_scales():
    assert set(benchmark.TASKS) == {"small", "medium", "large"}
    plain_source = benchmark.CapPacket.__init__.__code__.co_varnames
    assert "batching" in plain_source


def test_scale_packet_does_not_inject_large_monthly_contract(tmp_path):
    packet = benchmark.CapPacket(
        tmp_path, benchmark.TASKS["small"]["goal"], {}, 8, batching=False)
    assert "/reports/summary" in packet.render()
    assert '"month":"YYYY-MM"' not in packet.render()
    assert "/reports/monthly" not in packet.render()
