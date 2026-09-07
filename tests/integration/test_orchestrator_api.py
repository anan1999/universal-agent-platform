import asyncio

from fastapi.testclient import TestClient

from adaptive_agent import __version__
from adaptive_agent.api.app import create_app
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.storage.database import Database


def test_mock_goal_persists_and_api_replays(tmp_path):
    db = Database(tmp_path / "test.db")
    bus = EventBus(db)
    run_id = asyncio.run(Orchestrator(db, MockProvider(delay=0), bus).run_goal("Add INT8 QNN pipeline"))
    client = TestClient(create_app(db, bus))
    detail = client.get(f"/api/runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "completed"
    assert detail.json()["tasks"]
    assert client.get("/api/token-usage", params={"run_id": run_id}).json()
    assert client.get("/api/routing", params={"run_id": run_id}).json()
    assert client.get("/api/performance").json()
    assert client.get("/api/efficiency", params={"run_id": run_id}).status_code == 200
    assert client.get("/api/health").json()["version"] == __version__
    task_id = detail.json()["tasks"][0]["id"]
    assert client.get(f"/api/tasks/{task_id}").json()["receipts"]
