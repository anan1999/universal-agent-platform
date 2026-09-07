import asyncio

from adaptive_agent.core.escalation import EscalationManager, FailureKind
from adaptive_agent.core.models import Receipt, Task
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.base import AIProvider
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph


class EscalatingFake(AIProvider):
    def __init__(self):
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def execute(self, task, progress=None, packet=None):
        self.calls += 1
        call_number = self.calls
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        if task.title == "escalate" and call_number == 1:
            return Receipt(task.id, task.owner, "failed", "uncertain", confidence="low", needs_escalation=True,
                           token_usage={"input": 10, "output": 5, "source": "estimated"}, model=task.metadata.get("model"))
        return Receipt(task.id, task.owner, "completed", "done", confidence="high",
                       token_usage={"input": 10, "output": 5, "source": "estimated"}, model=task.metadata.get("model"))


def insert(db, tasks):
    db.execute("INSERT INTO runs(id,goal,status) VALUES('R','goal','running')")
    for task in tasks:
        db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES(?,?,?,?,?,?,?)",
                   (task.id, task.run_id, task.title, task.owner, task.status.value, task.priority, db.json(task.to_dict())))


def test_escalation_budget_and_environment_classification():
    manager = EscalationManager(max_escalations=2)
    task = Task("T", "R", "x", "explorer", model_class="cheap")
    auth = Receipt("T", "explorer", "failed", "auth", error_code="CODEX_AUTH_ERROR", needs_escalation=True)
    assert manager.decide(task, auth, 0).failure_kind == FailureKind.ENVIRONMENT
    assert manager.decide(task, auth, 0).escalate is False
    uncertain = Receipt("T", "explorer", "failed", "uncertain", confidence="low", needs_escalation=True)
    assert manager.decide(task, uncertain, 0).escalate is True
    assert manager.decide(task, uncertain, 2).escalate is False


def test_scheduler_escalates_and_limits_parallelism(tmp_path):
    db = Database(tmp_path / "db.sqlite")
    provider = EscalatingFake()
    tasks = [
        Task("A", "R", "escalate", "explorer", model_class="cheap", metadata={"model": "mock-small", "task_type": "repository_search"}),
        Task("B", "R", "parallel", "tester", model_class="cheap", metadata={"model": "mock-small", "task_type": "build"}),
    ]
    insert(db, tasks)
    result = asyncio.run(Scheduler(db, EventBus(db), provider, max_parallel_agents=2).run(TaskGraph(tasks)))
    assert result is True
    assert provider.max_active == 2
    events = db.query("SELECT event FROM events")
    assert "task_escalating" in {row["event"] for row in events}
    assert len(db.query("SELECT * FROM agent_performance")) == 3


def test_scheduler_cancellation_marks_task(tmp_path):
    class Slow(AIProvider):
        async def execute(self, task, progress=None, packet=None):
            await asyncio.sleep(5)
            return Receipt(task.id, task.owner, "completed", "done")

    async def scenario():
        db = Database(tmp_path / "cancel.sqlite")
        task = Task("A", "R", "slow", "explorer")
        insert(db, [task])
        running = asyncio.create_task(Scheduler(db, EventBus(db), Slow()).run(TaskGraph([task])))
        await asyncio.sleep(0.02)
        running.cancel()
        try:
            await running
        except asyncio.CancelledError:
            pass
        return db.query("SELECT status FROM tasks WHERE id='A'")[0]["status"]

    assert asyncio.run(scenario()) == "cancelled"
