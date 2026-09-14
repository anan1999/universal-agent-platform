from pathlib import Path

from adaptive_agent.core.goal_analyzer import GoalAnalyzer
from adaptive_agent.core.models import Task, TaskKind
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.project.adaptive_budget import AdaptiveToolBudgetStore
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph
from adaptive_agent.cli import parser


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


def test_orchestrator_applies_learned_cap_and_explains_source(tmp_path):
    store = initialized(tmp_path)
    orchestrator = Orchestrator(
        Database(tmp_path / "platform.db"), MockProvider(delay=0),
        adaptive_tool_budget=True,
    )
    goal = "Build a FastAPI endpoint"
    current = orchestrator.analyzer.analyze(goal)
    for _ in range(3):
        store.record(current, accepted=True)
    composition = orchestrator.compose(
        "RUN-ADAPTIVE", goal, working_directory=str(tmp_path),
    )
    assert composition.execution_budget["max_provider_tool_calls"] == 6
    evidence = composition.project_intelligence["adaptive_tool_budget"]
    assert evidence["source"] == "accepted_history"
    assert evidence["accepted_runs"] == 3


def test_controller_acceptance_ignores_agent_claims_and_requires_real_tool_result(tmp_path):
    orchestrator = Orchestrator(Database(tmp_path / "platform.db"), MockProvider(delay=0))
    agent_only = Task("A", "RUN", "Model says done", "developer", kind=TaskKind.AGENT)
    assert orchestrator._external_acceptance(TaskGraph([agent_only]), True) is None

    passed = Task("T", "RUN", "Run tests", "project_test", kind=TaskKind.TOOL,
                  metadata={"tool": "project_test", "tool_result": {
                      "status": "completed", "exit_code": 0}})
    assert orchestrator._external_acceptance(TaskGraph([passed]), True) is True
    passed.metadata["tool_result"] = {"status": "failed", "exit_code": 1}
    assert orchestrator._external_acceptance(TaskGraph([passed]), False) is False


def test_adaptive_budget_is_an_explicit_cli_experiment():
    normal = parser().parse_args(["run", "Build an API", "--dry-run"])
    adaptive = parser().parse_args([
        "run", "Build an API", "--dry-run", "--adaptive-provider-tool-budget",
    ])
    assert normal.adaptive_provider_tool_budget is False
    assert adaptive.adaptive_provider_tool_budget is True
