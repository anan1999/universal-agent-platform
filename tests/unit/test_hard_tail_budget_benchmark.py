import importlib.util
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "hard_tail_budget_benchmark", ROOT / "scripts/hard_tail_budget_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, passed=True, tools=3, messages=3, seconds=10):
    return {
        "usage": {"input": tokens - 100, "output": 100, "cached": cached,
                  "source": "measured"},
        "quality": {"passed": passed}, "duration_seconds": seconds,
        "telemetry": {"tool_calls": tools, "assistant_messages": messages,
                      "assistant_message_chars": messages * 100},
    }


def test_hard_packet_and_runtime_limits_match(tmp_path):
    root = tmp_path / "fixture"
    shutil.copytree(benchmark.FIXTURE, root)
    context = benchmark.prepare(root, benchmark.GOAL)["context"]
    rendered = benchmark.TailBudgetPacket(root, benchmark.GOAL, context, "hard_3").render()
    assert "Hard envelope: 3 tool calls and 12 assistant messages" in rendered
    assert benchmark.LIMITS["hard_3"] == {
        "max_provider_tool_calls": 3, "max_provider_messages": 12}


def test_summary_preserves_quality_gate_and_cost_views():
    rounds = [{"round": 1, "order": list(benchmark.ARMS), "results": {
        "flexible_8": result(1000, 300, tools=4, messages=4),
        "hard_3": result(800, 200, tools=3, messages=3, seconds=8),
    }}]
    summary = benchmark.summarize(rounds)
    assert summary["pooled_total_token_reduction_percent"] == 20.0
    assert summary["pooled_tool_reduction_percent"] == 25.0
    assert summary["hard_quality_passes"] == 1
    rendered = benchmark.render({"summary": summary})
    assert "CANDIDATE" in rendered
    assert "Do not change the default budget" in rendered
    assert "deterministic external acceptance" in rendered


def test_unavailable_usage_is_rejected():
    assert benchmark.measurable({"usage": {
        "source": "measured", "input": 1, "output": 1}}) is True
    assert benchmark.measurable({"usage": {
        "source": "unavailable", "input": 0, "output": 0}}) is False
