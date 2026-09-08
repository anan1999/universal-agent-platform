import asyncio

from adaptive_agent.core.cross_provider_demo import cross_provider_demo
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.base import AIProvider, ProviderKind
from adaptive_agent.providers.registry import ProviderDescriptor, ProviderRegistry
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph


def test_cross_provider_demo_is_offline_and_capability_driven():
    result = cross_provider_demo()
    assert result["offline"] is True
    assert result["quota_consumed"] is False
    assert result["routes"]["product_planner"]["provider"] == "mock_api"
    assert result["routes"]["ui_reviewer"]["provider"] == "mock_api"
    developer = result["routes"]["developer"]
    assert developer["provider"] == "mock_agentic"
    assert any(item["provider"] == "mock_api" and item["disqualified"]
               for item in developer["candidates"])


def test_cross_provider_execution_preserves_dependency_receipt_handoff(tmp_path):
    calls = []

    class RecordingProvider(AIProvider):
        def __init__(self, provider_id):
            self.id = provider_id

        async def execute(self, task, progress=None, packet=None):
            rendered = packet.render()
            calls.append((self.id, task.id, rendered))
            return Receipt(task.id, task.owner, "completed", f"receipt from {self.id}",
                           token_usage={"input": 1, "output": 1, "source": "measured"},
                           provider=self.id, model=task.metadata.get("model"))

    api = RecordingProvider("mock_api")
    local = RecordingProvider("mock_agentic")
    registry = ProviderRegistry([
        ProviderDescriptor("mock_api", "Mock API", ProviderKind.TEST, lambda: api),
        ProviderDescriptor("mock_agentic", "Mock Agentic", ProviderKind.TEST, lambda: local),
    ])
    db = Database(tmp_path / "cross-provider.db")
    db.execute("INSERT INTO runs(id,goal,status) VALUES('RUN','goal','running')")
    tasks = [
        Task("PLAN", "RUN", "plan", "planner", metadata={"provider": "mock_api", "model": "api"}),
        Task("BUILD", "RUN", "build", "developer", dependencies=["PLAN"],
             metadata={"provider": "mock_agentic", "model": "local"}),
        Task("REVIEW", "RUN", "review", "reviewer", dependencies=["BUILD"],
             metadata={"provider": "mock_api", "model": "api"}),
    ]
    for task in tasks:
        db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES(?,?,?,?,?,?,?)",
                   (task.id, task.run_id, task.title, task.owner, task.status.value, task.priority,
                    db.json(task.to_dict())))
    assert asyncio.run(Scheduler(db, EventBus(db), api, provider_name="mock_api",
                                 provider_registry=registry).run(TaskGraph(tasks)))
    assert [(provider, task_id) for provider, task_id, _ in calls] == [
        ("mock_api", "PLAN"), ("mock_agentic", "BUILD"), ("mock_api", "REVIEW")]
    assert "receipt from mock_api" in calls[1][2]
    assert "receipt from mock_agentic" in calls[2][2]
