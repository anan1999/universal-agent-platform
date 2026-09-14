from pathlib import Path

from adaptive_agent.core.goal_analyzer import GoalAnalyzer
from adaptive_agent.project.adaptive_budget import AdaptiveToolBudgetStore


def analysis(goal: str = "Build a FastAPI endpoint"):
    return GoalAnalyzer().analyze(goal, active_profiles=("software-engineering",))


def initialized(root: Path) -> AdaptiveToolBudgetStore:
    (root / ".agent").mkdir()
    (root / ".agent" / "commands.yaml").write_text("commands: {}\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    return AdaptiveToolBudgetStore(root)


def test_requires_three_external_acceptances_before_recommending_cap(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    assert store.decide(current).provider_tool_cap is None
    for _ in range(2):
        assert store.record(current, accepted=True)
    assert store.decide(current).provider_tool_cap is None
    assert store.record(current, accepted=True)
    decision = store.decide(current)
    assert decision.provider_tool_cap == 6
    assert decision.accepted_runs == 3
    assert decision.source == "accepted_history"


def test_cap_tightens_in_bounded_steps_and_never_below_three(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for count in range(1, 13):
        store.record(current, accepted=True)
        expected = None if count < 3 else 6 if count < 6 else 4 if count < 9 else 3
        assert store.decide(current).provider_tool_cap == expected


def test_failure_resets_only_the_same_comparable_family(tmp_path):
    store = initialized(tmp_path)
    coding = analysis()
    research = analysis("Analyze a research question")
    for _ in range(3):
        store.record(coding, accepted=True)
        store.record(research, accepted=True)
    assert store.decide(coding).provider_tool_cap == 6
    assert store.record(coding, accepted=False)
    assert store.decide(coding).provider_tool_cap is None
    assert store.decide(research).provider_tool_cap == 6


def test_environment_change_invalidates_prior_evidence(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for _ in range(3):
        store.record(current, accepted=True)
    assert store.decide(current).provider_tool_cap == 6
    (tmp_path / "pyproject.toml").write_text("[project]\nname='changed'\n", encoding="utf-8")
    assert store.decide(current).provider_tool_cap is None


def test_explicit_cap_always_wins_without_reading_history(tmp_path):
    store = initialized(tmp_path)
    decision = store.decide(analysis(), explicit_cap=2)
    assert decision.provider_tool_cap == 2
    assert decision.source == "explicit"
