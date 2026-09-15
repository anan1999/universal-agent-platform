import asyncio

from adaptive_agent.core.models import Event, Receipt, Task, TaskKind, TaskStatus
from adaptive_agent.core.consumption import ExecutionBudget
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.core.tools import ToolExecutor, ToolResult
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


def test_scheduler_aggregates_measured_cost_for_adaptive_learning(tmp_path):
    class MeasuredProvider(MockProvider):
        async def execute(self, task, progress=None, packet=None):
            return Receipt(
                task.id, task.owner, "completed", "done", provider="codex",
                duration_seconds=2.5,
                token_usage={"input": 100, "output": 20, "cached": 60,
                             "source": "measured", "provider_tool_calls": 2,
                             "provider_messages": 1, "invocation_count": 1,
                             "attribution": {"method": "test", "windows": [
                                 {"kind": "after_command_execution", "total_tokens": 120}]}},
            )

    tasks = [Task("A", "R", "first", "worker"),
             Task("B", "R", "second", "worker", dependencies=["A"])]
    db, scheduler, result = _budget_graph(
        tmp_path, tasks, MeasuredProvider(delay=0), ExecutionBudget())
    assert result is True
    assert scheduler.adaptive_metrics() == {
        "source": "measured", "provider_tool_calls": 4, "provider_messages": 2,
        "total_tokens": 240, "uncached_tokens": 120, "duration_seconds": 5.0,
        "input_tokens": 200, "cached_input_tokens": 120,
        "uncached_input_tokens": 80, "output_tokens": 40,
        "provider_attempts": 2,
    }
    usage_rows = db.query(
        "SELECT provider_tool_calls,provider_messages,attribution_json FROM token_usage")
    assert [(row["provider_tool_calls"], row["provider_messages"])
            for row in usage_rows] == [(2, 1), (2, 1)]
    assert all('"after_command_execution"' in row["attribution_json"] for row in usage_rows)


def test_scheduler_refuses_estimated_cost_as_learning_evidence(tmp_path):
    tasks = [Task("A", "R", "first", "worker")]
    _, scheduler, result = _budget_graph(
        tmp_path, tasks, MockProvider(delay=0), ExecutionBudget())
    assert result is True
    assert scheduler.adaptive_metrics() == {"source": "unavailable"}


def _budget_graph(tmp_path, tasks, provider, budget):
    db = Database(tmp_path / "budget.db")
    db.execute("INSERT INTO runs(id,goal,status) VALUES('R','goal','running')")
    for task in tasks:
        db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES(?,?,?,?,?,?,?)",
                   (task.id, task.run_id, task.title, task.owner, task.status.value,
                    task.priority, db.json(task.to_dict())))
    scheduler = Scheduler(db, EventBus(db), provider, execution_budget=budget)
    result = asyncio.run(scheduler.run(TaskGraph(tasks)))
    return db, scheduler, result


def test_provider_call_budget_hard_stops_later_task(tmp_path):
    tasks = [Task("A", "R", "first", "worker"),
             Task("B", "R", "second", "reviewer", dependencies=["A"])]
    provider = MockProvider(delay=0)
    db, scheduler, result = _budget_graph(
        tmp_path, tasks, provider, ExecutionBudget(max_provider_calls=1))
    assert result is False
    assert provider.usage().invocation_count == 1
    assert scheduler.budget_status()["provider_calls_used"] == 1
    receipt = db.query("SELECT data_json FROM receipts WHERE task_id='B'")[0]
    assert 'BUDGET_EXHAUSTED' in receipt["data_json"]
    assert any(row["event"] == "budget_exhausted" for row in db.query("SELECT event FROM events"))


def test_zero_retry_budget_prevents_second_provider_call(tmp_path):
    task = Task("A", "R", "fail", "worker", model_class="cheap")
    provider = MockProvider(delay=0, fail_titles={"fail"})
    db, scheduler, result = _budget_graph(
        tmp_path, [task], provider, ExecutionBudget(max_provider_calls=5, max_retry_rounds=0))
    assert result is False
    assert provider.usage().invocation_count == 1
    assert scheduler.budget_status()["provider_calls_used"] == 1
    assert any(row["event"] == "budget_retry_suppressed"
               for row in db.query("SELECT event FROM events"))


def test_token_preflight_rejects_input_that_cannot_fit(tmp_path):
    task = Task("A", "R", "large request", "worker")
    provider = MockProvider(delay=0)
    db, scheduler, result = _budget_graph(
        tmp_path, [task], provider,
        ExecutionBudget(max_total_tokens=10, verification_reserve_percent=0))
    assert result is False
    assert provider.usage().invocation_count == 0
    event = db.query("SELECT metadata_json FROM events WHERE event='budget_exhausted'")[0]
    assert "token budget" in event["metadata_json"]


def test_parent_validation_uses_one_provider_call_then_zero_ai_tool(monkeypatch, tmp_path):
    agent = Task("A", "R", "implement", "worker",
                 metadata={"parent_validation_tools": ["project_test"]})
    validation = Task("V", "R", "validate", "project_test", dependencies=["A"],
                      kind=TaskKind.TOOL,
                      metadata={"tool": "project_test", "working_directory": str(tmp_path)})
    monkeypatch.setattr(ToolExecutor, "run", lambda self, tool: ToolResult(
        "project_test", "completed", "Project Test succeeded.", exit_code=0))
    provider = MockProvider(delay=0)
    db, scheduler, result = _budget_graph(
        tmp_path, [agent, validation], provider, ExecutionBudget(max_provider_calls=1))
    assert result is True
    assert provider.usage().invocation_count == 1
    assert scheduler.budget_status()["tool_calls_used"] == 1
    invocations = db.query("SELECT task_id,invocation_count FROM token_usage ORDER BY task_id")
    assert [(row["task_id"], row["invocation_count"]) for row in invocations] == [("A", 1), ("V", 0)]


def test_parent_validation_failure_does_not_trigger_another_provider_call(monkeypatch, tmp_path):
    agent = Task("A", "R", "implement", "worker",
                 metadata={"parent_validation_tools": ["project_test"]})
    validation = Task("V", "R", "validate", "project_test", dependencies=["A"],
                      kind=TaskKind.TOOL,
                      metadata={"tool": "project_test", "working_directory": str(tmp_path)})
    monkeypatch.setattr(ToolExecutor, "run", lambda self, tool: ToolResult(
        "project_test", "failed", "Project Test exited 1.", exit_code=1))
    provider = MockProvider(delay=0)
    _, scheduler, result = _budget_graph(
        tmp_path, [agent, validation], provider, ExecutionBudget(max_provider_calls=1))
    assert result is False
    assert provider.usage().invocation_count == 1
    assert scheduler.budget_status()["tool_calls_used"] == 1

