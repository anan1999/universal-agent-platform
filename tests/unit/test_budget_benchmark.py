import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("budget_benchmark", ROOT / "scripts/budget_benchmark.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


def test_budget_pair_changes_only_resource_contract(tmp_path):
    baseline = benchmark.BudgetPacket(tmp_path, benchmark.GOAL, False)
    budgeted = benchmark.BudgetPacket(tmp_path, benchmark.GOAL, True)
    assert budgeted.render().startswith(baseline.render())
    addition = budgeted.render()[len(baseline.render()):]
    assert "at most 8 observable tool calls" in addition
    assert "acceptance validation" in addition
    assert baseline.working_directory == budgeted.working_directory


def test_report_states_advisory_boundary():
    empty = {"quality": {"passed": True}, "usage": {}, "telemetry": {}, "duration_seconds": 0}
    report = {"goal": benchmark.GOAL, "results": {"unbounded": empty, "budgeted": empty},
              "conclusion": "sample", "limitations": ["internal cap is advisory"]}
    rendered = benchmark.render_report(report)
    assert "internal cap is advisory" in rendered
    assert "Problem" in rendered


def test_budget_first_counterbalance_is_cli_visible():
    assert benchmark.execution_order(False) == ["unbounded", "budgeted"]
    assert benchmark.execution_order(True) == ["budgeted", "unbounded"]
