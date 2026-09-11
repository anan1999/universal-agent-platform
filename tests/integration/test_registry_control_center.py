import asyncio

from fastapi.testclient import TestClient

from adaptive_agent.api.app import create_app
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.storage.database import Database


def test_registry_apis_bind_agents_skills_and_profiles(tmp_path):
    db = Database(tmp_path / "registry.db")
    bus = EventBus(db)
    client = TestClient(create_app(db, bus))
    agents = client.get("/api/agents").json()
    explorer = next(item for item in agents if item["id"] == "explorer")
    assert explorer["provider_profile"] == "luna_worker"
    assert {"repository_search", "git"} <= set(explorer["skills"])
    assert client.get("/api/agents/explorer").status_code == 200
    assert client.get("/api/agents/explorer/skills").status_code == 200
    skills = client.get("/api/skills").json()
    assert next(item for item in skills if item["id"] == "qnn")["scope"] == "global"
    assert client.get("/api/skills/qnn").json()["token_attribution"] == "unavailable"
    assert client.patch("/api/codex/profiles", json={}).status_code == 404


def test_generic_skill_labels_are_not_loaded_as_procedure_skills(tmp_path):
    db = Database(tmp_path / "runtime.db")
    bus = EventBus(db)
    asyncio.run(Orchestrator(db, MockProvider(delay=0), bus,
                             active_profiles=["software-engineering"]).run_goal(
        "Search the repository and report relevant files. Do not modify anything."))
    client = TestClient(create_app(db, bus))
    selected_skill = client.get("/api/skills/repository_search").json()
    assert selected_skill["load_count"] == 0
    assert selected_skill["loaded"] is False
    assert selected_skill["used_by_agents"] == ["explorer"], \
        "registry declarations remain visible even when no procedure package is loaded"
    assert client.get("/api/skills/git").json()["load_count"] == 0, \
        "progressive loading must not inherit every Skill declared by a role"
    usage = client.get("/api/skills/repository_search/usage").json()
    assert usage["history"] == []
    run_id = db.query("SELECT id FROM runs ORDER BY created_at DESC LIMIT 1")[0]["id"]
    run_skills = client.get(f"/api/runs/{run_id}/skills").json()
    assert run_skills == []
    assert client.get("/api/runs/DOES-NOT-EXIST/skills").status_code == 404


def test_agent_disable_safety_and_temporary_promotion_data(tmp_path):
    db = Database(tmp_path / "controls.db")
    db.execute("INSERT INTO agents(name,type,status,data_json) VALUES('ota_specialist','temporary','enabled',?)",
               (db.json({"capabilities": ["android_ota"], "successful_uses": 3, "promotion_candidate": True}),))
    db.execute("INSERT INTO runs(id,goal,status) VALUES('RUN-X','work','running')")
    db.execute("INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json) VALUES('TASK-X','RUN-X','Work','explorer','running',1,'{}')")
    client = TestClient(create_app(db, EventBus(db)))
    temporary = next(item for item in client.get("/api/agents").json() if item["id"] == "ota_specialist")
    assert temporary["promotion_candidate"] is True
    assert client.patch("/api/agents/explorer", json={"enabled": False}).status_code == 409
    assert client.patch("/api/agents/tester", json={"enabled": False}).json()["enabled"] is False
    assert client.patch("/api/skills/qnn", json={"enabled": False}).json()["enabled"] is False


def test_skill_intelligence_api_exposes_candidates_and_artifact_results(tmp_path):
    db = Database(tmp_path / "skill-api.db")
    client = TestClient(create_app(db, EventBus(db)))
    candidates = client.get("/api/skill-candidates", params={"capability": "w8a8 validation"}).json()
    assert candidates[0]["skill"] == "w8a8-validation"
    db.execute("INSERT INTO artifact_evaluations(run_id,task_id,evaluator,passed,quality_json) "
               "VALUES('RUN-A','TASK-A','declared_artifacts',1,?)",
               (db.json({"passed": True, "correctness": 1.0}),))
    evaluations = client.get("/api/artifact-evaluations", params={"run_id": "RUN-A"}).json()
    assert evaluations[0]["quality"]["correctness"] == 1.0
