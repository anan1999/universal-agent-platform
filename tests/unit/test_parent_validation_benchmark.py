import importlib.util
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "parent_validation_benchmark", ROOT / "scripts/parent_validation_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def result(tokens, cached, passed=True, tools=4, seconds=10, parent_tools=0,
           validation_actions=0):
    return {
        "usage": {"input": tokens - 100, "output": 100, "cached": cached,
                  "source": "measured"},
        "quality": {"passed": passed}, "provider_duration_seconds": seconds,
        "end_to_end_seconds": seconds + parent_tools,
        "telemetry": {"tool_calls": tools, "assistant_messages": 2,
                      "assistant_message_chars": 200,
                      "actions": [{"labels": ["validation"]}] * validation_actions},
        "parent_validation": {"tool_calls": parent_tools},
    }


def test_summary_counts_zero_ai_parent_tool_separately():
    rounds = [{"round": 1, "order": list(benchmark.ARMS), "results": {
        "agent_owned": result(1000, 300, tools=5, validation_actions=1),
        "parent_owned": result(800, 200, tools=3, seconds=8, parent_tools=1,
                               validation_actions=2),
    }}]
    summary = benchmark.summarize(rounds)
    assert summary["pooled_total_token_reduction_percent"] == 20.0
    assert summary["pooled_provider_tool_reduction_percent"] == 40.0
    assert summary["pooled"]["parent_owned"]["parent_tool_calls"] == 1
    assert summary["pooled"]["parent_owned"]["provider_validation_actions"] == 2
    assert summary["agent_quality_passes"] == summary["parent_quality_passes"] == 1


def test_parent_packet_removes_command_and_assigns_scheduler(tmp_path):
    root = tmp_path / "fixture"
    shutil.copytree(benchmark.FIXTURE, root)
    benchmark._configure(root)
    context = benchmark.prepare(root, benchmark.GOAL)["context"]
    control = benchmark.OwnershipPacket(root, benchmark.GOAL, context, False).render()
    treatment = benchmark.OwnershipPacket(root, benchmark.GOAL, context, True).render()
    assert "commands_to_verify" in control
    assert "commands_to_verify" not in treatment
    assert "Run the project-wide test suite once" in control
    assert "scheduler runs project_test" in treatment


def test_unavailable_provider_usage_is_not_measurable():
    assert benchmark.measurable({"usage": {
        "source": "measured", "input": 10, "output": 2}}) is True
    assert benchmark.measurable({"usage": {
        "source": "unavailable", "input": 0, "output": 0}}) is False


def test_render_rejects_uniform_cost_regression():
    rounds = [{"round": 1, "order": list(benchmark.ARMS), "results": {
        "agent_owned": result(1000, 300, tools=2),
        "parent_owned": result(1200, 300, tools=3, seconds=12, parent_tools=1),
    }}]
    report = {"summary": benchmark.summarize(rounds)}
    rendered = benchmark.render(report)
    assert "REJECT_COST" in rendered
    assert "UAP_EXPERIMENTAL_PARENT_VALIDATION" in rendered
    assert "child execution interface" in rendered
