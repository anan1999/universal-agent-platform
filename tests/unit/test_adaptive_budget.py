import asyncio
import sys
from pathlib import Path

import yaml

from adaptive_agent.core.goal_analyzer import GoalAnalyzer
from adaptive_agent.core.models import Receipt, Task, TaskKind
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


def measured(tools: int = 3, total: int = 1000, uncached: int = 400,
             seconds: float = 10) -> dict:
    return {"source": "measured", "provider_tool_calls": tools,
            "total_tokens": total, "uncached_tokens": uncached,
            "duration_seconds": seconds}


def test_requires_three_external_acceptances_before_recommending_cap(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    assert store.decide(current).provider_tool_cap is None
    for _ in range(2):
        assert store.record(current, accepted=True, metrics=measured())
    assert store.decide(current).provider_tool_cap is None
    assert store.record(current, accepted=True, metrics=measured())
    decision = store.decide(current)
    assert decision.provider_tool_cap == 6
    assert decision.accepted_runs == 3
    assert decision.source == "accepted_history"


def test_cap_tightens_only_when_each_stage_preserves_measured_cost(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for _ in range(3):
        store.record(current, True, measured(tools=5, total=1000, uncached=400))
    assert store.decide(current).provider_tool_cap == 6
    for _ in range(3):
        store.record(current, True, measured(tools=4, total=800, uncached=300), effective_cap=6)
    assert store.decide(current).provider_tool_cap == 4
    for _ in range(3):
        store.record(current, True, measured(tools=3, total=700, uncached=250), effective_cap=4)
    decision = store.decide(current)
    assert decision.provider_tool_cap == 3
    assert decision.cost_gate == "cap_3_supported_by_cost"


def test_success_without_measured_cost_never_tightens(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for _ in range(9):
        store.record(current, accepted=True)
    decision = store.decide(current)
    assert decision.accepted_runs == 9
    assert decision.provider_tool_cap is None
    assert decision.cost_gate == "insufficient_cost_evidence"


def test_cost_regression_blocks_next_tightening_step(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for _ in range(3):
        store.record(current, True, measured(tools=5, total=1000, uncached=400))
    for _ in range(3):
        store.record(current, True, measured(tools=3, total=1200, uncached=500), effective_cap=6)
    decision = store.decide(current)
    assert decision.accepted_runs == 6
    assert decision.provider_tool_cap == 6
    assert decision.cost_gate == "cap_6_supported"


def test_failure_resets_only_the_same_comparable_family(tmp_path):
    store = initialized(tmp_path)
    coding = analysis()
    research = analysis("Analyze a research question")
    for _ in range(3):
        store.record(coding, accepted=True, metrics=measured())
        store.record(research, accepted=True, metrics=measured())
    assert store.decide(coding).provider_tool_cap == 6
    assert store.record(coding, accepted=False)
    assert store.decide(coding).provider_tool_cap is None
    assert store.decide(research).provider_tool_cap == 6


def test_environment_change_invalidates_prior_evidence(tmp_path):
    store = initialized(tmp_path)
    current = analysis()
    for _ in range(3):
        store.record(current, accepted=True, metrics=measured())
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
        store.record(current, accepted=True, metrics=measured())
    composition = orchestrator.compose(
        "RUN-ADAPTIVE", goal, working_directory=str(tmp_path),
    )
    assert composition.execution_budget["max_provider_tool_calls"] == 6
    evidence = composition.project_intelligence["adaptive_tool_budget"]
    assert evidence["source"] == "accepted_history"
    assert evidence["accepted_runs"] == 3


def test_controller_acceptance_ignores_agent_claims_and_requires_real_tool_result(tmp_path):
    initialized(tmp_path)
    orchestrator = Orchestrator(Database(tmp_path / "platform.db"), MockProvider(delay=0))
    agent_only = Task("A", "RUN", "Model says done", "developer", kind=TaskKind.AGENT)
    assert orchestrator._external_acceptance(TaskGraph([agent_only]), True) is None

    passed = Task("T", "RUN", "Run tests", "project_test", kind=TaskKind.TOOL,
                  metadata={"tool": "project_test", "working_directory": str(tmp_path),
                            "tool_result": {
                      "status": "completed", "exit_code": 0}})
    # Ordinary tests are not assumed to cover the requested change.
    assert orchestrator._external_acceptance(TaskGraph([passed]), True) is None
    (tmp_path / ".agent" / "commands.yaml").write_text(
        "commands:\n  test:\n    command: [python, -m, pytest, -q]\n    acceptance: true\n",
        encoding="utf-8",
    )
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


def test_three_real_scheduler_acceptances_apply_cap_on_the_next_run(tmp_path):
    class MeasuredProvider(MockProvider):
        async def execute(self, task, progress=None, packet=None):
            return Receipt(
                task.id, task.owner, "completed", "implemented", provider="mock",
                duration_seconds=1.0,
                token_usage={"input": 800, "output": 100, "cached": 500,
                             "source": "measured", "provider_tool_calls": 3,
                             "provider_messages": 2, "invocation_count": 1},
            )

    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent/commands.yaml").write_text(yaml.safe_dump({"commands": {
        "test": {"command": [sys.executable, "-c", "print('accepted')"],
                 "timeout": 20, "acceptance": True},
    }}), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='closed-loop'\n", encoding="utf-8")
    database = Database(tmp_path / "platform.db")
    goal = "Fix a simple Python arithmetic bug and run the existing test"
    for number in range(1, 4):
        orchestrator = Orchestrator(
            database, MeasuredProvider(delay=0), adaptive_tool_budget=True,
        )
        run_id = asyncio.run(orchestrator.run_goal(
            goal, working_directory=str(tmp_path), run_id=f"RUN-{number}",
        ))
        assert database.query("SELECT status FROM runs WHERE id=?", (run_id,))[0]["status"] == "completed"

    next_orchestrator = Orchestrator(
        database, MeasuredProvider(delay=0), adaptive_tool_budget=True,
    )
    composition = next_orchestrator.compose(
        "RUN-4", goal, working_directory=str(tmp_path),
    )
    assert composition.execution_budget["max_provider_tool_calls"] == 6
    decision = composition.project_intelligence["adaptive_tool_budget"]
    assert decision["accepted_runs"] == 3
    assert decision["cost_samples"] == 3
    assert decision["cost_gate"] == "cap_6_supported"
