from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.observability.performance import PerformanceTracker
from adaptive_agent import __version__
from adaptive_agent.runtime import RESOURCE_ROOT, database
from adaptive_agent.registry_view import (
    agents as registry_agents, model_registry, profiles as registry_profiles,
    providers as registry_providers, skills as registry_skills, tools as registry_tools,
)
from adaptive_agent.project.adapter import UAP_START, orchestration_config, project_profiles
from adaptive_agent.storage.database import Database


def create_app(db: Database | None = None, events: EventBus | None = None) -> FastAPI:
    db = db or database()
    events = events or EventBus(db)
    app = FastAPI(title="Universal Agent Platform", version=__version__)
    app.state.database = db
    app.state.events = events

    def decoded(rows: list[dict], field: str = "data_json") -> list[dict]:
        for row in rows:
            if field in row:
                row["data"] = json.loads(row.pop(field))
        return rows

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/bootstrap-status")
    def bootstrap_status():
        project = Path.cwd()
        installed = all((RESOURCE_ROOT / relative).exists() for relative in (
            "config/models.yaml", "config/profiles/general.yaml",
            "templates/capabilities.yaml", "dashboard/index.html"))
        agents_path = project / "AGENTS.md"
        marker = agents_path.is_file() and UAP_START in agents_path.read_text(encoding="utf-8")
        initialized = ((project / ".agent" / "project.yaml").is_file() and marker and
                       orchestration_config(project)["owner"] == "universal-agent-platform")
        provider_items = registry_providers(db)
        active = project_profiles(project) if initialized else []
        return {
            "platform_installation": "ready" if installed else "fail",
            "project_initialization": "ready" if initialized else "not_initialized",
            "provider_availability": sum(1 for item in provider_items if item["ready"]),
            "profiles_active": len(active),
            "health": "pass" if installed else "fail",
        }

    @app.get("/api/projects")
    def projects():
        return decoded(db.query("SELECT * FROM projects ORDER BY created_at DESC"), "config_json")

    @app.get("/api/runs")
    def runs(project_id: str | None = None):
        sql, params = ("SELECT * FROM runs WHERE project_id=? ORDER BY created_at DESC", (project_id,)) if project_id else ("SELECT * FROM runs ORDER BY created_at DESC", ())
        return db.query(sql, params)

    @app.get("/api/runs/{run_id}")
    def run(run_id: str):
        rows = db.query("SELECT * FROM runs WHERE id=?", (run_id,))
        if not rows:
            raise HTTPException(404, "run not found")
        result = rows[0]
        result["tasks"] = decoded(db.query("SELECT * FROM tasks WHERE run_id=? ORDER BY priority DESC", (run_id,)))
        result["events"] = decoded(db.query("SELECT * FROM events WHERE run_id=? ORDER BY timestamp", (run_id,)), "metadata_json")
        return result

    @app.get("/api/tasks")
    def tasks(run_id: str | None = None):
        return decoded(db.query("SELECT * FROM tasks WHERE run_id=? ORDER BY priority DESC", (run_id,)) if run_id else db.query("SELECT * FROM tasks ORDER BY rowid DESC LIMIT 500"))

    @app.get("/api/tasks/{task_id}")
    def task(task_id: str):
        rows = decoded(db.query("SELECT * FROM tasks WHERE id=?", (task_id,)))
        if not rows:
            raise HTTPException(404, "task not found")
        result = rows[0]
        result["receipts"] = decoded(db.query("SELECT * FROM receipts WHERE task_id=?", (task_id,)))
        return result

    @app.get("/api/agents")
    def agents():
        return registry_agents(db)

    @app.get("/api/agents/{agent_id}")
    def agent(agent_id: str):
        matches = [item for item in registry_agents(db) if item["id"] == agent_id]
        if not matches:
            raise HTTPException(404, "agent not found")
        result = matches[0]
        result["recent_runs"] = db.query("SELECT task_id,status,data_json,created_at FROM receipts WHERE agent=? ORDER BY id DESC LIMIT 20", (agent_id,))
        result["mailbox"] = decoded(db.query("SELECT * FROM messages WHERE sender=? OR recipient=? ORDER BY rowid DESC LIMIT 20", (agent_id, agent_id)))
        return result

    @app.get("/api/agents/{agent_id}/skills")
    def agent_skills(agent_id: str):
        return [item for item in registry_skills(db) if agent_id in item["used_by_agents"]]

    @app.get("/api/agents/{agent_id}/performance")
    def agent_performance(agent_id: str):
        return [item for item in PerformanceTracker(db).metrics() if item["agent_role"] == agent_id]

    @app.patch("/api/agents/{agent_id}")
    def update_agent(agent_id: str, payload: dict):
        matches = [item for item in registry_agents(db) if item["id"] == agent_id]
        if not matches:
            raise HTTPException(404, "agent not found")
        current = matches[0]
        enabled = bool(payload.get("enabled", current["enabled"]))
        if not enabled and current["status"] == "working":
            raise HTTPException(409, "cannot disable an executing agent")
        db.execute("INSERT OR REPLACE INTO agents(name,type,status,data_json) VALUES(?,?,?,?)",
                   (agent_id, current["type"], "enabled" if enabled else "disabled", db.json({})))
        return [item for item in registry_agents(db) if item["id"] == agent_id][0]

    @app.get("/api/skills")
    def skills():
        return registry_skills(db)

    @app.get("/api/skills/{skill_id}")
    def skill(skill_id: str):
        matches = [item for item in registry_skills(db) if item["id"] == skill_id]
        if not matches:
            raise HTTPException(404, "skill not found")
        return matches[0]

    @app.get("/api/skills/{skill_id}/agents")
    def skill_agents(skill_id: str):
        skill = next((item for item in registry_skills(db) if item["id"] == skill_id), None)
        if not skill:
            raise HTTPException(404, "skill not found")
        return [item for item in registry_agents(db) if item["id"] in skill["used_by_agents"]]

    @app.get("/api/skills/{skill_id}/usage")
    def skill_usage(skill_id: str):
        return {"history": db.query("SELECT * FROM agent_skills WHERE skill_id=? ORDER BY loaded_at DESC", (skill_id,)),
                "token_attribution": "unavailable"}

    @app.patch("/api/skills/{skill_id}")
    def update_skill(skill_id: str, payload: dict):
        matches = [item for item in registry_skills(db) if item["id"] == skill_id]
        if not matches:
            raise HTTPException(404, "skill not found")
        current = matches[0]
        enabled = bool(payload.get("enabled", current["enabled"]))
        if not enabled and current["loaded"]:
            raise HTTPException(409, "cannot disable a currently loaded skill")
        db.execute("INSERT OR REPLACE INTO skills(name,enabled,data_json) VALUES(?,?,?)",
                   (skill_id, int(enabled), db.json({})))
        return [item for item in registry_skills(db) if item["id"] == skill_id][0]

    # -- V2 registries -----------------------------------------------------

    @app.get("/api/providers")
    def providers():
        return registry_providers(db)

    @app.get("/api/providers/{provider_id}")
    def provider(provider_id: str):
        matches = [item for item in registry_providers(db) if item["id"] == provider_id]
        if not matches:
            raise HTTPException(404, "provider not found")
        result = matches[0]
        result["models"] = [item.to_dict() for item in model_registry().for_provider(provider_id)]
        return result

    @app.get("/api/providers/{provider_id}/profiles")
    def provider_native_profiles(provider_id: str):
        """Provider-native agent configurations. Read-only; never universal Agents."""
        from adaptive_agent.registry_view import provider_profiles

        return provider_profiles(provider_id)

    @app.get("/api/models")
    def models(provider: str | None = None):
        catalog = model_registry()
        selected = catalog.for_provider(provider) if provider else catalog.all()
        return [item.to_dict() for item in selected]

    @app.get("/api/profiles")
    def work_profiles():
        active = set(project_profiles(Path.cwd()))
        return [{**item, "active": item["id"] in active} for item in registry_profiles()]

    @app.get("/api/profiles/{profile_id}")
    def work_profile(profile_id: str):
        matches = [item for item in registry_profiles() if item["id"] == profile_id]
        if not matches:
            raise HTTPException(404, "profile not found")
        return {**matches[0], "active": profile_id in set(project_profiles(Path.cwd()))}

    @app.get("/api/tools")
    def tools_list():
        return registry_tools()

    @app.get("/api/plugins")
    def plugins():
        """Installed plugins, listed without loading any of them."""
        from adaptive_agent.plugins import discover
        from adaptive_agent.runtime import platform_home

        return discover(platform_home() / "plugins")

    @app.get("/api/runs/{run_id}/composition")
    def composition(run_id: str):
        """Why this team, and why each provider. The explainability payload."""
        rows = db.query("SELECT goal,composition_json,work_profiles FROM runs WHERE id=?", (run_id,))
        if not rows:
            raise HTTPException(404, "run not found")
        stored = db.loads(rows[0].get("composition_json"))
        routing = []
        for row in db.query("SELECT id,title,owner,data_json FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,)):
            metadata = json.loads(row.pop("data_json")).get("metadata", {})
            routing.append({**row, "routing": metadata.get("routing", {}),
                            "provider": metadata.get("provider"), "model": metadata.get("model")})
        return {"run_id": run_id, "goal": rows[0]["goal"],
                "work_profiles": [item for item in str(rows[0].get("work_profiles", "")).split(",") if item],
                "analysis": stored.get("analysis", {}), "team": stored.get("team", {}),
                "routing": routing}

    @app.get("/api/orchestration")
    def orchestration():
        return {**orchestration_config(Path.cwd()), "orchestrator": "Universal Agent Platform",
                "child_guard": "ready"}

    @app.get("/api/events")
    def event_list(run_id: str | None = None, limit: int = Query(200, ge=1, le=1000)):
        rows = db.query("SELECT * FROM events WHERE run_id=? ORDER BY timestamp DESC LIMIT ?", (run_id, limit)) if run_id else db.query("SELECT * FROM events ORDER BY timestamp DESC LIMIT ?", (limit,))
        return decoded(rows, "metadata_json")

    @app.get("/api/token-usage")
    def tokens(run_id: str | None = None):
        where, params = (" WHERE run_id=?", (run_id,)) if run_id else ("", ())
        return db.query(f"SELECT run_id,task_id,agent,SUM(input_tokens) input_tokens,SUM(output_tokens) output_tokens,SUM(cached_tokens) cached_tokens,SUM(input_tokens+output_tokens) total_tokens,MAX(estimated) estimated,token_source FROM token_usage{where} GROUP BY run_id,task_id,agent,token_source", params)

    @app.get("/api/performance")
    def performance():
        return PerformanceTracker(db).metrics()

    @app.get("/api/routing")
    def routing(run_id: str | None = None):
        rows = db.query("SELECT id,run_id,title,data_json FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,)) if run_id else db.query("SELECT id,run_id,title,data_json FROM tasks ORDER BY rowid DESC LIMIT 200")
        result = []
        for row in rows:
            data = json.loads(row.pop("data_json"))
            result.append({**row, "routing": data.get("metadata", {}).get("routing", {})})
        return result

    @app.get("/api/efficiency")
    def efficiency(run_id: str | None = None):
        rows = db.query("SELECT id,run_id,data_json FROM tasks WHERE run_id=?", (run_id,)) if run_id else db.query("SELECT id,run_id,data_json FROM tasks ORDER BY rowid DESC LIMIT 200")
        warnings = []
        for row in rows:
            data = json.loads(row["data_json"])
            for warning in data.get("metadata", {}).get("efficiency_warnings", []):
                warnings.append({"task_id": row["id"], "run_id": row["run_id"], **warning})
        return warnings

    @app.get("/api/capabilities")
    def capabilities():
        temporary = db.query("SELECT * FROM agents WHERE type='temporary'")
        return {"missing": [], "temporary_specialists": decoded(temporary), "promotion_candidates": [row for row in decoded(db.query("SELECT * FROM agents")) if row.get("data", {}).get("promotion_candidate")]}

    @app.get("/api/events/live")
    async def live_events():
        async def stream():
            yield "event: connected\ndata: {}\n\n"
            iterator = events.subscribe().__aiter__()
            while True:
                try:
                    event = await asyncio.wait_for(iterator.__anext__(), 15)
                    yield f"data: {json.dumps(event.to_dict())}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    dashboard = RESOURCE_ROOT / "dashboard"
    if dashboard.exists():
        app.mount("/assets", StaticFiles(directory=dashboard), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dashboard / "index.html")

        @app.get("/agents")
        @app.get("/skills")
        @app.get("/tools")
        @app.get("/providers")
        @app.get("/profiles")
        def registry_index():
            return FileResponse(dashboard / "index.html")
    return app
