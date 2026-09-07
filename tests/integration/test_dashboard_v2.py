"""V2 dashboard API: providers, profiles, tools, and the explainability payload.

The dashboard is the only place a user sees *why* the platform did what it did,
so these routes are part of the product surface rather than debug output.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from adaptive_agent.api.app import create_app
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.storage.database import Database


@pytest.fixture
def client(tmp_path):
    db = Database(tmp_path / "dashboard.db")
    return TestClient(create_app(db, EventBus(db)))


@pytest.fixture
def run(tmp_path):
    db = Database(tmp_path / "run.db")
    bus = EventBus(db)
    orchestrator = Orchestrator(db, MockProvider(delay=0), bus)
    run_id = asyncio.run(orchestrator.run_goal("Redesign the settings page for better usability",
                                               working_directory=str(tmp_path)))
    return TestClient(create_app(db, bus)), run_id


# -- Providers ---------------------------------------------------------------

def test_providers_report_state_without_exposing_secrets(client):
    payload = client.get("/api/providers").json()
    assert payload, "at least the built-in providers must be registered"
    identifiers = {item["id"] for item in payload}
    assert {"codex", "mock"} <= identifiers
    for item in payload:
        assert item["status"] in {"available", "installed", "configured", "connected",
                                  "unavailable", "unsupported"}
        assert set(item["capabilities"].values()) <= {"supported", "unsupported",
                                                      "model_dependent", "unknown"}
        serialized = str(item).lower()
        assert "api_key" not in serialized and "secret" not in serialized


def test_unimplemented_providers_are_not_presented_as_working(client):
    payload = {item["id"]: item for item in client.get("/api/providers").json()}
    assert payload["mock"]["implemented"] is True
    for provider_id in ("openai", "anthropic", "gemini", "ollama"):
        provider = payload[provider_id]
        assert provider["implemented"] is False
        assert provider["ready"] is False, f"{provider_id} must never claim readiness"


def test_provider_detail_lists_its_models(client):
    payload = client.get("/api/providers/mock").json()
    assert payload["id"] == "mock"
    assert payload["models"], "the mock provider has a catalogued model set"
    assert all(model["provider"] == "mock" for model in payload["models"])


def test_unknown_provider_is_a_404(client):
    assert client.get("/api/providers/nonexistent").status_code == 404


def test_provider_native_profiles_are_scoped_to_their_provider(client):
    """Codex profiles are a provider convention, never universal Agents."""
    assert client.get("/api/providers/openai/profiles").json() == []
    assert client.get("/api/providers/codex/profiles").status_code == 200
    assert client.get("/api/codex/profiles").status_code == 404


# -- Models ------------------------------------------------------------------

def test_models_can_be_filtered_by_provider(client):
    every = client.get("/api/models").json()
    mock_only = client.get("/api/models", params={"provider": "mock"}).json()
    assert every and mock_only
    assert len(mock_only) < len(every)
    assert {item["provider"] for item in mock_only} == {"mock"}


# -- Work profiles -----------------------------------------------------------

def test_profiles_expose_roles_skills_and_evaluation(client):
    payload = {item["id"]: item for item in client.get("/api/profiles").json()}
    assert len(payload) == 10
    software = payload["software-engineering"]
    assert software["roles"] and software["capabilities"]
    assert software["evaluation_strategies"]
    assert software["source"], "a profile must say where it came from, so it can be edited"


def test_profile_detail_and_unknown_profile(client):
    assert client.get("/api/profiles/uiux").json()["id"] == "uiux"
    assert client.get("/api/profiles/interior-design").status_code == 404


# -- Tools -------------------------------------------------------------------

def test_tools_declare_risk_and_execution_type(client):
    payload = client.get("/api/tools").json()
    assert payload
    for tool in payload:
        assert tool["risk"] in {"safe", "low", "moderate", "high", "destructive"}
        assert tool["execution"] in {"project_command", "builtin_command", "internal", "manual"}


# -- Plugins -----------------------------------------------------------------

def test_plugins_route_lists_nothing_when_none_are_installed(client):
    assert client.get("/api/plugins").json() == []


# -- Explainability ----------------------------------------------------------

def test_composition_answers_why_this_team(run):
    client, run_id = run
    payload = client.get(f"/api/runs/{run_id}/composition").json()
    assert payload["run_id"] == run_id
    team = payload["team"]
    assert team["members"], "the run must record who was on the team"
    assert team["rationale"], "the run must record why"
    assert all(member["reason"] for member in team["members"])
    assert payload["analysis"]["capabilities"]


def test_composition_answers_why_this_provider(run):
    client, run_id = run
    payload = client.get(f"/api/runs/{run_id}/composition").json()
    agent_tasks = [item for item in payload["routing"] if item["routing"].get("model")]
    assert agent_tasks, "at least one task must have been routed to a model"
    for task in agent_tasks:
        decision = task["routing"]
        assert decision["provider"] and decision["reason"]
        assert "always uses" not in decision["reason"].lower()


def test_composition_records_omissions_not_just_selections(run):
    client, run_id = run
    team = client.get(f"/api/runs/{run_id}/composition").json()["team"]
    assert team["omitted"], "roles left out must be explained, not silently dropped"
    assert all(item["role"] and item["reason"] for item in team["omitted"])


def test_composition_of_unknown_run_is_a_404(client):
    assert client.get("/api/runs/RUN-NOPE/composition").status_code == 404


# -- Routing -----------------------------------------------------------------

def test_dashboard_pages_are_served(client):
    for path in ("/", "/agents", "/skills", "/tools", "/providers", "/profiles"):
        assert client.get(path).status_code == 200, f"{path} should serve the dashboard"
