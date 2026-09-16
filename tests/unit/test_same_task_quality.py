import shutil
from pathlib import Path

import pytest

from scripts.same_task_quality import GOALS, evaluate
from scripts.same_task_long_dialogue_benchmark import summary


ROOT = Path(__file__).resolve().parents[2]


def test_goals_are_ten_coherent_medication_planner_followups():
    assert len(GOALS) == 10
    assert all(goal and len(goal) < 500 for goal in GOALS)
    assert all(any(term in goal.lower() for term in
                   ("medication", "schedule", "search", "form", "prototype", "dialog"))
               for goal in GOALS)


def test_quality_is_cumulative_and_rejects_missing_extensions(tmp_path):
    shutil.copytree(ROOT / "benchmark-fixtures" / "cross-domain" / "ui-ux", tmp_path / "project")
    first = evaluate(tmp_path / "project", 1)
    tenth = evaluate(tmp_path / "project", 10)
    assert not first["passed"] and not tenth["passed"]
    assert "base_contract" in first["checks"]
    assert "local_persistence_and_disclosure" in tenth["errors"]


def test_pilot_artifact_still_satisfies_early_contracts_if_available():
    if not shutil.which("node"):
        pytest.skip("node is needed for JS syntax checks")
    prior = ROOT / ".benchmark-same-task-dialogue-sol-20260916-r3" / "uap"
    if not (prior / "prototype.html").exists():
        pytest.skip("local historical evidence is not part of the package")
    assert evaluate(prior, 1)["passed"]
    assert evaluate(prior, 2)["passed"]
    assert evaluate(prior, 3)["passed"]
    assert not evaluate(prior, 4)["passed"]


def test_summary_does_not_claim_quality_from_partial_dialogue():
    rows = [{"usage": {"total_tokens": 100, "uncached_tokens": 25,
                       "cached_input_tokens": 75}, "seconds": 1.0,
             "quality": {"passed": True}}]
    result = summary(rows, 10)
    assert result["turns_completed"] == 1
    assert result["final_contract_passed"] is False
    assert result["total_tokens"] == 100
