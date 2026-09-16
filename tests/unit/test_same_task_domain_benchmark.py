from pathlib import Path
import json

import pytest

from scripts.same_task_domain_benchmark import CONFIG, prompt_for, summarize
from scripts.same_task_domain_quality import EVALUATORS, GOALS, _xyz
from scripts.rescore_same_task_animation import rescore
from scripts.export_same_task_report import export


def test_two_domains_have_ten_related_prompts_and_separate_artifacts():
    assert set(GOALS) == {"programming", "animation"}
    assert all(len(goals) == 10 for goals in GOALS.values())
    assert CONFIG["programming"]["artifact"] != CONFIG["animation"]["artifact"]
    assert "ExpenseTracker" in GOALS["programming"][0]
    assert "scene_at" in GOALS["animation"][0]
    assert all(goal and len(goal) < 700 for goals in GOALS.values() for goal in goals)


def test_initial_artifacts_fail_and_checks_are_cumulative(tmp_path):
    for domain in GOALS:
        early = EVALUATORS[domain](tmp_path, 1)
        late = EVALUATORS[domain](tmp_path, 10)
        assert not early["passed"] and not late["passed"]
        assert early["errors"]


def test_uap_prompt_keeps_user_goal_and_baseline_remains_short(tmp_path):
    goal = GOALS["programming"][0]
    baseline = prompt_for("baseline", "programming", tmp_path, goal)
    uap = prompt_for("uap", "programming", tmp_path, goal)
    assert goal in baseline and goal in uap
    assert "developer" in uap.casefold()
    assert len(baseline) < len(uap)


def test_partial_dialogue_never_claims_final_quality():
    rows = [{"usage": {"total_tokens": 12, "uncached_tokens": 5,
                       "cached_input_tokens": 7}, "seconds": 1,
             "quality": {"passed": True}}]
    result = summarize(rows, 10)
    assert result["turns"] == 1 and not result["final_contract_passed"]
    assert result["total_tokens"] == 12


def test_3d_position_accepts_equivalent_scene_node_representation():
    assert _xyz((1, 2, 3)) == (1.0, 2.0, 3.0)
    assert _xyz({"position": [1, 2, 3], "radius": 0.5}) == (1.0, 2.0, 3.0)


def test_rescore_rejects_wrong_domain_without_rewriting_source(tmp_path):
    report = tmp_path / "report.json"
    original = json.dumps({"domain": "programming", "arms": {}})
    report.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        rescore(tmp_path)
    assert report.read_text(encoding="utf-8") == original
    assert not (tmp_path / "rescore.json").exists()


def test_public_export_omits_thread_ids_and_absolute_paths(tmp_path):
    row = {"number": 1, "status": "completed", "usage": {
        "total_tokens": 10, "uncached_tokens": 3, "cached_input_tokens": 7},
        "seconds": 1.5, "quality": {"passed": True, "errors": []},
        "artifact_sha256": "abc", "turn_id": "secret-turn-id"}
    report = {"domain": "programming", "model": "sol", "reasoning": "low",
              "prompts": ["goal"], "comparison_valid": True,
              "arms": {arm: {"thread_id": "secret-thread-id", "turns": [row]}
                       for arm in ("baseline", "uap")}}
    (tmp_path / "report.json").write_text(json.dumps(report), encoding="utf-8")
    result = export(tmp_path)
    assert result["arms"]["uap"]["total_tokens"] == 10
    assert "secret" not in json.dumps(result)
    assert str(tmp_path) not in json.dumps(result)
