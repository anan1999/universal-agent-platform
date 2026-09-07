import asyncio

from adaptive_agent.core.models import Event, Task, TaskStatus
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph


def test_graph_dependency_resolution_and_cycle_detection(tmp_path):
    first = Task("A", "R", "first", "explorer")
    second = Task("B", "R", "second", "developer", dependencies=["A"])
    graph = TaskGraph([first, second])
    assert [task.id for task in graph.ready()] == ["A"]
    first.status = TaskStatus.COMPLETED
    assert [task.id for task in graph.ready()] == ["B"]
    first.dependencies = ["B"]
    try:
        graph.validate()
        assert False, "cycle must fail"
    except ValueError as error:
        assert "cycle" in str(error)


def test_scheduler_emits_events_receipts_and_tokens(tmp_path):
    db = Database(tmp_path / "test.db")
    db.execute("INSERT INTO runs(id,goal,status) VALUES('R','goal','running')")
    tasks = [Task("A", "R", "explore", "explorer"), Task("B", "R", "build", "developer", dependencies=["A"])]
    for task in tasks:
        db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES(?,?,?,?,?,?,?)", (task.id,task.run_id,task.title,task.owner,task.status.value,task.priority,db.json(task.to_dict())))
    assert asyncio.run(Scheduler(db, EventBus(db), MockProvider(delay=0)).run(TaskGraph(tasks)))
    assert len(db.query("SELECT * FROM receipts")) == 2
    assert len(db.query("SELECT * FROM token_usage")) == 2
    assert {row["event"] for row in db.query("SELECT * FROM events")} >= {"task_started", "task_completed", "receipt_created"}

