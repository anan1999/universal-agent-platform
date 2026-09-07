from adaptive_agent.core.capabilities import Requirement
from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.models.registry import ModelRegistry
from adaptive_agent.observability.efficiency import TokenEfficiencyAnalyzer
from adaptive_agent.observability.performance import PerformanceTracker
from adaptive_agent.providers.registry import default_registry
from adaptive_agent.runtime import PACKAGE_ROOT
from adaptive_agent.storage.database import Database

def _router(database):
    return CapabilityRouter(ModelRegistry.from_yaml(PACKAGE_ROOT / "config" / "models.yaml"),
                            default_registry(), database, preferences=["mock"])


def test_routing_decision_is_capability_first(tmp_path):
    router = _router(Database(tmp_path / "db.sqlite"))
    first = router.route([Requirement("repository_search")], agent_role="explorer")
    second = router.route([Requirement("repository_search")], agent_role="writer")
    assert first.model == second.model
    assert first.provider == second.provider == "mock"


def test_performance_history_and_conservative_adaptation(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    tracker = PerformanceTracker(db)
    task = Task("T", "R", "search", "analyst", ["repository_search"],
                metadata={"task_type": "repository_search", "provider": "mock"})
    for index in range(5):
        tracker.record(task, Receipt("T", "analyst", "completed" if index == 0 else "failed", "x",
                                     token_usage={"input": 100, "output": 20, "source": "measured"},
                                     model="mock-small", escalated=index > 0))
    metrics = tracker.metrics()[0]
    assert metrics["task_count"] == 5
    assert metrics["sufficient_history"] is True
    decision = _router(db).route([Requirement("repository_search")], agent_role="analyst")
    assert decision.model != "mock-small"
    assert decision.historical_samples == 5


def test_efficiency_warning_for_strong_mechanical_task():
    task = Task("T", "R", "search", "explorer", model_class="strong", metadata={"task_type": "repository_search"})
    warnings = TokenEfficiencyAnalyzer().analyze(task)
    assert warnings[0].code == "STRONG_FOR_MECHANICAL"
