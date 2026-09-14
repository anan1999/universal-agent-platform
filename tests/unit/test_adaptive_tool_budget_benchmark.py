import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "adaptive_tool_budget_benchmark", ROOT / "scripts/adaptive_tool_budget_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, tools, seconds=10, passed=True):
    return {"usage": {"input": tokens - 100, "output": 100, "cached": cached,
                       "source": "measured"},
            "quality": {"passed": passed}, "duration_seconds": seconds,
            "telemetry": {"tool_calls": tools, "assistant_messages": 3}}


def rounds():
    values = []
    for number in range(1, 7):
        values.append({
            "round": number,
            "order": list(benchmark.ARMS if number % 2 else reversed(benchmark.ARMS)),
            "adaptive_cap": 8 if number <= 3 else 6,
            "adaptive_decision": {"accepted_runs": max(0, number - 1)},
            "results": {
                "fixed_8": result(1000, 300, 4),
                "adaptive": result(900 if number >= 4 else 1000, 250, 3),
            },
        })
    return values


def test_summary_separates_learning_cost_from_post_learning_effect():
    summary = benchmark.summarize(rounds())
    assert summary["cumulative"]["rounds"] == 6
    assert summary["post_learning"]["rounds"] == 3
    assert summary["post_learning"]["total_token_reduction_percent"] == 10.0
    assert summary["post_learning"]["tool_reduction_percent"] == 25.0
    assert summary["post_learning"]["fixed_quality"] == 3
    assert summary["post_learning"]["adaptive_quality"] == 3


def test_report_uses_post_learning_quality_and_both_token_views():
    report = {"rounds": rounds(), "summary": benchmark.summarize(rounds())}
    rendered = benchmark.render(report)
    assert "Post-learning rounds 4–6" in rendered
    assert "Decision: **CANDIDATE**" in rendered
    assert "subscription quota" in rendered


def test_reset_refuses_target_outside_dedicated_workspace(tmp_path):
    outside = tmp_path.parent / "outside-adaptive-benchmark"
    try:
        benchmark._reset(outside, tmp_path / "workspace", preserve_learning=False)
    except RuntimeError as error:
        assert "leaves its dedicated workspace" in str(error)
    else:
        raise AssertionError("unsafe reset target was accepted")


def test_real_result_is_converted_to_production_cost_evidence():
    current = result(1000, 300, 4, seconds=12)
    assert benchmark.adaptive_metrics(current) == {
        "source": "measured", "provider_tool_calls": 4,
        "total_tokens": 1000, "uncached_tokens": 700,
        "duration_seconds": 12,
    }
