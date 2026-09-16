from pathlib import Path

from scripts.same_task_domain_benchmark import CONFIG, prompt_for, summarize
from scripts.same_task_domain_quality import EVALUATORS, GOALS


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
