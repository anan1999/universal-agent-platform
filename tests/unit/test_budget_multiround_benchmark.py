import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "budget_multiround", ROOT / "scripts/budget_multiround_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def arm(tokens, cached, tools, seconds, passed=True):
    return {"quality": {"passed": passed},
            "usage": {"input": tokens, "output": 100, "cached": cached},
            "telemetry": {"tool_calls": tools, "assistant_messages": 2,
                          "assistant_message_chars": 100},
            "duration_seconds": seconds}


def test_summary_uses_paired_medians_and_uncached_tokens():
    reports = [
        {"order": ["unbounded", "budgeted"],
         "results": {"unbounded": arm(1000, 500, 5, 10),
                     "budgeted": arm(800, 400, 3, 8)}},
        {"order": ["budgeted", "unbounded"],
         "results": {"unbounded": arm(1200, 600, 6, 12),
                     "budgeted": arm(900, 500, 4, 9)}},
    ]
    summary = benchmark.summarize(reports)
    assert summary["rounds_completed"] == 2
    assert summary["budget_token_win_rounds"] == 2
    assert summary["budget_uncached_token_win_rounds"] == 2
    assert summary["mean_tool_call_delta"] == 2
    assert summary["all_quality_equal_and_passed"] is True
