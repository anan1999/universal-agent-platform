import importlib.util
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "silent_validation_memory_benchmark",
    ROOT / "scripts/silent_validation_memory_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, passed=True, tools=4, messages=3, seconds=10):
    return {"usage": {"input": tokens - 100, "output": 100, "cached": cached,
                      "source": "measured"},
            "quality": {"passed": passed}, "duration_seconds": seconds,
            "telemetry": {"tool_calls": tools, "assistant_messages": messages,
                          "assistant_message_chars": messages * 100}}


def test_summary_keeps_quality_gate_and_measured_savings_separate():
    rounds = [{"round": 1, "order": list(benchmark.ARMS), "results": {
        "cold_candidates": result(1000, 300, passed=True),
        "silent_memory": result(800, 200, passed=False, tools=3, messages=2, seconds=8),
    }}]
    summary = benchmark.summarize(rounds)
    assert summary["pooled_total_token_reduction_percent"] == 20.0
    assert summary["cold_quality_passes"] == 1
    assert summary["warm_quality_passes"] == 0
    assert summary["pooled_tool_call_reduction_percent"] == 25.0


def test_zero_ai_training_silently_reduces_command_candidates(tmp_path):
    roots = {name: tmp_path / name for name in benchmark.ARMS}
    for root in roots.values():
        shutil.copytree(benchmark.FIXTURE, root)
        benchmark._configure(root)
        benchmark.prepare(root, benchmark.GOAL)
    training = benchmark._train_pair(roots)
    contexts = {
        arm: benchmark.prepare(root, benchmark.GOAL, use_experience=arm == "silent_memory")
        for arm, root in roots.items()
    }
    assert not training["cold_candidates"]["saved"]
    assert training["silent_memory"]["saved"] is True
    assert training["silent_memory"]["ai_calls"] == 0
    assert set(contexts["cold_candidates"]["context"]["commands_to_verify"]) == {
        "test", "build", "frontend_build"}
    assert set(contexts["silent_memory"]["context"]["commands_to_verify"]) == {"test"}
    assert "verified_procedures" not in contexts["silent_memory"]["context"]
