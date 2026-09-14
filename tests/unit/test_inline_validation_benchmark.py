import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "inline_validation_benchmark", ROOT / "scripts/inline_validation_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, passed=True, tools=4, messages=3, seconds=10):
    return {"usage": {"input": tokens - 100, "output": 100, "cached": cached,
                      "source": "measured"},
            "quality": {"passed": passed}, "duration_seconds": seconds,
            "telemetry": {"tool_calls": tools, "assistant_messages": messages,
                          "assistant_message_chars": messages * 100}}


def test_declared_packet_names_one_exact_validation_command(tmp_path):
    packet = benchmark.DeclaredValidationPacket(tmp_path, "goal", {"source_pointers": []})
    rendered = packet.render()
    assert benchmark.VALIDATION_COMMAND in rendered
    assert "exit status as authoritative" in rendered
    assert "focused repair" not in rendered


def test_summary_keeps_quality_separate_from_cost():
    rounds = [{"round": 1, "order": list(benchmark.ARMS), "results": {
        "generic_validation": result(1000, 500, passed=True),
        "declared_validation": result(800, 400, passed=False, tools=3, messages=2, seconds=8),
    }}]
    summary = benchmark.summarize(rounds)
    assert summary["pooled_total_token_reduction_percent"] == 20.0
    assert summary["generic_quality_passes"] == 1
    assert summary["declared_quality_passes"] == 0
    assert summary["declared_quality_regressions"] == 1
