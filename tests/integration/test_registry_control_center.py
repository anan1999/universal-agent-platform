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


def test_runtime_skill_associations_are_history_not_permanent_loads(tmp_path):
    db = Database(tmp_path / "runtime.db")
    bus = EventBus(db)
    asyncio.run(Orchestrator(db, MockProvider(delay=0), bus,
                             active_profiles=["software-engineering"]).run_goal(
        "Inspect repository files and report relevant code. Do not modify anything."))
    client = TestClient(create_app(db, bus))
    git_skill = client.get("/api/skills/git").json()
    assert git_skill["load_count"] == 1
    assert git_skill["loaded"] is False
    assert "developer" in git_skill["used_by_agents"]
    usage = client.get("/api/skills/git/usage").json()
    assert usage["history"][0]["source"] == "runtime"


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
