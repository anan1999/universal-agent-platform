import importlib.util
import argparse
import asyncio
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("pi_benchmark", ROOT / "scripts/pi_budget_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, tools=4, messages=2, seconds=10):
    return {
        "usage": {"input": tokens - 100, "output": 100, "cached": cached},
        "telemetry": {"tool_calls": tools, "assistant_messages": messages,
                      "assistant_message_chars": messages * 100},
        "duration_seconds": seconds,
        "quality": {"passed": True},
    }


def test_summary_compares_pi_context_against_same_budget():
    rounds = [
        {"round": 1, "order": ["budget_only", "pi_context"],
         "results": {"budget_only": result(1000, 100), "pi_context": result(800, 100, 3, 1, 8)}},
        {"round": 2, "order": ["pi_context", "budget_only"],
         "results": {"budget_only": result(1200, 200), "pi_context": result(900, 200, 3, 1, 8)}},
    ]
    summary = benchmark.summarize(rounds)
    assert summary["all_quality_equal_and_passed"]
    assert summary["pi_total_token_win_rounds"] == 2
    assert summary["pi_uncached_token_win_rounds"] == 2
    assert summary["pooled_total_token_reduction_percent"] > 0
    assert summary["pooled_tool_call_reduction_percent"] == 25.0


def test_value_gated_packet_does_not_claim_pointer_is_content(tmp_path):
    packet = benchmark.PiBudgetPacket(
        tmp_path, "goal", {"source_pointers": [{"path": "src/app.py"}]})
    assert "Pointers are routing hints" in packet.render()
    assert "supplied excerpts as the first inspection" not in packet.render()


def test_resume_rejects_parameter_drift_before_provider_call(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    output = tmp_path / "evidence.json"
    output.write_text(json.dumps({
        "goal": benchmark.GOAL,
        "model": "different-model",
        "context_budget_chars": 4000,
        "context_strategy": "value_gated",
        "rounds": [],
    }), encoding="utf-8")
    args = argparse.Namespace(
        workspace=workspace, output=output, report=tmp_path / "report.md",
        rounds=10, context_budget=4000, value_gated=True,
        model="gpt-5.6-luna", timeout=300, resume=True,
    )
    with pytest.raises(SystemExit, match="model"):
        asyncio.run(benchmark.run(args))


def test_measurable_pair_requires_usage_from_both_arms():
    complete = {
        "results": {
            "budget_only": {"usage": {"input": 10, "source": "measured"}},
            "pi_context": {"usage": {"input": 9, "source": "measured"}},
        }
    }
    incomplete = {
        "results": {
            "budget_only": {"usage": {"input": 10, "source": "measured"}},
            "pi_context": {"usage": {"source": "unavailable"}},
        }
    }
    assert benchmark.measurable_pair(complete)
    assert not benchmark.measurable_pair(incomplete)
