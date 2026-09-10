import asyncio
import json

from fastapi.testclient import TestClient

from adaptive_agent.api.app import create_app
from adaptive_agent.cli import main, parser
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.intelligence.project import ProjectIntelligenceStore
from adaptive_agent.intelligence.project import IntelligenceItem
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.project.adapter import initialize_project
from adaptive_agent.project.discovery import discover
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.runtime import RESOURCE_ROOT
from adaptive_agent.storage.database import Database, SCHEMA_VERSION


def initialized_project(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='lifecycle'\n", encoding="utf-8")
    initialize_project(project, RESOURCE_ROOT / "templates", auto=True)
    return project


def test_cold_run_distills_evidence_and_next_run_is_warm(tmp_path):
    project = initialized_project(tmp_path)
    db = Database(tmp_path / "history.db")
    db.execute("INSERT INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
               ("PRJ-1", str(project), "project", "python", "{}"))
    info = discover(project)
    orchestrator = Orchestrator(db, MockProvider(delay=0), EventBus(db))

    first = asyncio.run(orchestrator.run_goal(
        "Test the Python service", "PRJ-1", str(project), project_name=info.name,
        project_type=info.type, project_signals=info.signals))
    second = asyncio.run(orchestrator.run_goal(
        "Improve Python tests", "PRJ-1", str(project), project_name=info.name,
        project_type=info.type, project_signals=info.signals))

    rows = db.query("SELECT run_id,temperature,reuse_hits FROM project_intelligence_runs ORDER BY id")
    assert rows[0] == {"run_id": first, "temperature": "cold", "reuse_hits": 0}
    assert rows[1]["run_id"] == second
    assert rows[1]["temperature"] == "warm"
    assert rows[1]["reuse_hits"] >= 1
    kinds = {item.kind for item in ProjectIntelligenceStore(project).items()}
    assert {"knowledge", "command", "receipt"} <= kinds


def test_changed_project_signal_forces_revalidation_run(tmp_path):
    project = initialized_project(tmp_path)
    store = ProjectIntelligenceStore(project)
    store.learn_discovery(discover(project), "RUN-COLD")
    (project / "pyproject.toml").write_text("[project]\nname='changed'\n", encoding="utf-8")
    selection = store.select("test python", record_reuse=True)
    assert selection.temperature == "revalidation"
    assert "project-discovery" in selection.stale_items


def test_context_reaches_execution_packet_metadata(tmp_path):
    project = initialized_project(tmp_path)
    store = ProjectIntelligenceStore(project)
    store.learn_discovery(discover(project), "RUN-COLD")
    db = Database(tmp_path / "packet.db")
    composition = Orchestrator(db, MockProvider(delay=0), EventBus(db)).plan(
        "RUN-PLAN", "test the Python project", str(project), "project", "python")
    agent_tasks = [task for task in composition.graph.tasks.values() if task.kind.value == "agent"]
    assert agent_tasks
    assert agent_tasks[0].metadata["project_intelligence"]["items"]
    assert composition.to_dict()["project_intelligence"]["temperature"] == "warm"


def test_validated_project_role_replaces_equivalent_generated_role(tmp_path):
    project = initialized_project(tmp_path)
    store = ProjectIntelligenceStore(project)
    store.add(IntelligenceItem(
        id="project-test-maintainer", kind="agent",
        summary="Maintain this project's Python tests and implementation conventions.",
        capabilities=["testing", "implementation"], tags=["python"],
        evidence=["reused successfully in prior project tasks"],
        validation="validated", expected_reuse=3))
    db = Database(tmp_path / "role.db")
    composition = Orchestrator(db, MockProvider(delay=0), EventBus(db)).plan(
        "RUN-ROLE", "Implement and test a Python service change", str(project), "project", "python")
    assert any(member.origin == "project_intelligence" for member in composition.team.members)
    assert any("no equivalent role was regenerated" in reason for reason in composition.team.rationale)


def test_cli_exposes_warm_start_resume_and_context(tmp_path, monkeypatch, capsys):
    project = initialized_project(tmp_path)
    monkeypatch.chdir(project)
    choices = next(action.choices for action in parser()._actions if action.choices)
    assert {"warm-start", "resume", "context"} <= set(choices)
    assert main(["warm-start", "test python", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["temperature"] == "cold"
    assert main(["context", "explain", "test python", "--json"]) == 0
    assert "estimated_tokens" in json.loads(capsys.readouterr().out)


def test_api_exposes_intelligence_status_and_context(tmp_path, monkeypatch):
    project = initialized_project(tmp_path)
    monkeypatch.chdir(project)
    db = Database(tmp_path / "api.db")
    client = TestClient(create_app(db, EventBus(db)))
    assert client.get("/api/project-intelligence").json()["status"]["level"] == 0
    response = client.get("/api/context/explain", params={"goal": "test python"})
    assert response.status_code == 200
    assert response.json()["temperature"] == "cold"
    assert "project_intelligence" in client.get("/api/bootstrap-status").json()


def test_schema_v7_is_additive(tmp_path):
    db = Database(tmp_path / "schema.db")
    assert SCHEMA_VERSION == 7
    assert db.query("SELECT version FROM schema_migrations WHERE version=7")
    columns = {row["name"] for row in db.query("PRAGMA table_info(project_intelligence_runs)")}
    assert {"temperature", "reuse_hits", "context_chars", "estimated_tokens"} <= columns
