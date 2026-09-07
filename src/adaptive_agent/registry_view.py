"""Read models for the CLI and the dashboard.

This is a presentation layer. It may show provider-specific conventions (such as
a Codex agent profile bound to a role) because a human wants to see them. The
capability router never reads any of it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.evaluation import EvaluationRegistry
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.models.registry import ModelRegistry
from adaptive_agent.profiles.registry import profile_registry
from adaptive_agent.providers.registry import providers as provider_registry
from adaptive_agent.runtime import PACKAGE_ROOT, platform_home
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.storage.database import Database


#: Agent kinds the dashboard must keep visually distinct (see docs/agent-model.md).
KIND_LOGICAL = "core"
KIND_SPECIALIST = "specialist"
KIND_TEMPORARY = "temporary"


def _title(name: str) -> str:
    return name.replace("_", " ").title()


def _profile_role_ids() -> dict[str, str]:
    """Role id -> the Work Profile that declares it."""
    return {role.id: role.profile for profile in profile_registry().all() for role in profile.roles}


def agents(db: Database) -> list[dict[str, Any]]:
    from adaptive_agent.providers.codex import codex_profile_for

    configured = AgentRegistry.from_yaml(PACKAGE_ROOT / "config" / "default_agents.yaml").all()
    declared_by_profile = _profile_role_ids()
    overrides = {row["name"]: row for row in db.query("SELECT * FROM agents")}
    running = {row["owner"]: row for row in db.query(
        "SELECT id,run_id,title,owner,data_json FROM tasks WHERE status='running' ORDER BY rowid DESC")}
    usage = {row["agent"]: row for row in db.query(
        "SELECT agent,SUM(input_tokens+output_tokens) tokens,MAX(estimated) estimated,"
        "SUM(invocation_count) invocations FROM token_usage GROUP BY agent")}
    perf = {row["agent_role"]: row for row in db.query(
        "SELECT agent_role,COUNT(*) runs,AVG(success) success_rate,AVG(input_tokens+output_tokens) avg_tokens,"
        "MAX(timestamp) last_used,MAX(provider) provider FROM agent_performance GROUP BY agent_role")}
    result = []
    for name, spec in configured.items():
        override = overrides.get(name)
        if override:
            spec.update(json.loads(override["data_json"]))
            spec["status"] = override["status"]
            spec["type"] = override["type"]
        task = running.get(name)
        status = "working" if task else ("disabled" if spec.get("status") == "disabled" else "idle")
        kind = KIND_LOGICAL if spec.get("type", "permanent") == "permanent" else spec.get("type", KIND_SPECIALIST)
        metric = perf.get(name, {})
        # The provider is resolved per task by the capability router. `auto`
        # means "whatever the router picks", which is the correct default.
        provider = metric.get("provider") or "auto"
        result.append({"id": name, "name": _title(name), "role": name, "type": kind,
                       "status": status, "provider": provider,
                       "provider_profile": spec.get("provider_profile") or codex_profile_for(name),
                       "model": spec.get("preferred_model") or "auto",
                       "reasoning": spec.get("reasoning"),
                       "work_profile": spec.get("profile") or declared_by_profile.get(name, "general"),
                       "capabilities": spec.get("capabilities", []), "skills": spec.get("skills", []),
                       "scope": spec.get("scope", "global"), "source": str(PACKAGE_ROOT / "config" / "default_agents.yaml"),
                       "enabled": status != "disabled", "current_task": task,
                       "project_id": None, "context_health": "healthy",
                       "token_usage": usage.get(name, {}).get("tokens", 0),
                       "token_estimated": bool(usage.get(name, {}).get("estimated", 0)),
                       "invocations": usage.get(name, {}).get("invocations", 0) or 0,
                       "success_rate": metric.get("success_rate"), "run_count": metric.get("runs", 0),
                       "average_tokens": metric.get("avg_tokens"), "last_used": metric.get("last_used"),
                       "promotion_candidate": bool(spec.get("promotion_candidate")),
                       "successful_uses": int(spec.get("successful_uses", 0))})
    for name, row in overrides.items():
        if name in configured:
            continue
        spec = json.loads(row["data_json"])
        metric = perf.get(name, {})
        result.append({"id": name, "name": _title(name), "role": name, "type": row["type"],
                       "status": row["status"], "provider": spec.get("provider") or metric.get("provider") or "auto",
                       "provider_profile": spec.get("provider_profile"), "model": spec.get("preferred_model") or "auto",
                       "reasoning": spec.get("reasoning"),
                       "work_profile": spec.get("profile") or declared_by_profile.get(name, "temporary"),
                       "capabilities": spec.get("capabilities", []),
                       "skills": spec.get("skills", []), "scope": spec.get("scope", "project"),
                       "source": spec.get("source", "Adaptive registry"), "enabled": row["status"] != "disabled",
                       "current_task": running.get(name), "project_id": spec.get("project_id"),
                       "context_health": spec.get("context_health", "healthy"), "token_usage": 0,
                       "token_estimated": False, "invocations": 0,
                       "success_rate": metric.get("success_rate"), "run_count": metric.get("runs", 0),
                       "average_tokens": None, "last_used": metric.get("last_used"),
                       "promotion_candidate": bool(spec.get("promotion_candidate")),
                       "successful_uses": int(spec.get("successful_uses", 0))})
    return sorted(result, key=lambda item: (item["type"] != KIND_LOGICAL, item["name"]))


def skills(db: Database) -> list[dict[str, Any]]:
    configured = SkillRegistry.from_yaml(PACKAGE_ROOT / "config" / "default_skills.yaml").all()
    overrides = {row["name"]: row for row in db.query("SELECT * FROM skills")}
    associations = db.query("SELECT * FROM agent_skills ORDER BY loaded_at DESC")
    agent_specs = {item["id"]: item for item in agents(db)}
    result = []
    for name, spec in configured.items():
        override = overrides.get(name)
        if override:
            spec.update(json.loads(override["data_json"]))
        history = [row for row in associations if row["skill_id"] == name]
        used_by = sorted({agent["id"] for agent in agent_specs.values() if name in agent["skills"]} |
                         {row["agent_id"] for row in history})
        result.append({"id": name, "name": _title(name), "description": spec.get("description", ""),
                       "scope": spec.get("scope", "built-in"), "source": str(PACKAGE_ROOT / "config" / "default_skills.yaml"),
                       "capabilities": spec.get("capabilities", []),
                       "enabled": bool(override["enabled"]) if override else spec.get("enabled", True),
                       "lazy_load": bool(spec.get("lazy", True)), "loaded": any(row["loaded"] for row in history),
                       "loaded_by": sorted({row["agent_id"] for row in history if row["loaded"]}),
                       "used_by_agents": used_by, "load_count": len(history),
                       "last_loaded": history[0]["loaded_at"] if history else None,
                       "recent_tasks": [row["task_id"] for row in history[:8]],
                       "token_attribution": "unavailable"})
    return sorted(result, key=lambda item: item["name"])


def provider_profiles(provider: str = "codex") -> list[dict[str, Any]]:
    """Provider-native agent configurations, imported read-only."""
    if provider != "codex":
        return []
    from adaptive_agent.providers.codex import CodexAgentConfigAdapter, provider_bindings

    bound = provider_bindings("codex").get("role_profiles", {})
    by_profile: dict[str, list[str]] = {}
    for role, profile_name in bound.items():
        by_profile.setdefault(profile_name, []).append(role)
    return [{"id": item.name, "name": item.name, "description": item.description,
             "model": item.model, "reasoning": item.reasoning, "source": item.source_path,
             "provider": "codex", "bound_to": sorted(by_profile.get(item.name, [])),
             "read_only": True, "warning": item.warning}
            for item in CodexAgentConfigAdapter().discover(Path.home() / ".codex")]


def providers(db: Database | None = None) -> list[dict[str, Any]]:
    """Every registered adapter and its honest readiness state. Never exposes secrets."""
    discovered = provider_registry().discover()
    models = model_registry()
    usage = {}
    if db is not None:
        usage = {row["provider"]: row for row in db.query(
            "SELECT provider,SUM(input_tokens+output_tokens) tokens,SUM(invocation_count) invocations "
            "FROM token_usage WHERE provider != '' GROUP BY provider")}
        success = {row["provider"]: row for row in db.query(
            "SELECT provider,COUNT(*) runs,AVG(success) success_rate FROM agent_performance "
            "WHERE provider != '' GROUP BY provider")}
    else:
        success = {}
    for item in discovered:
        item["models"] = [model.to_dict() for model in models.for_provider(item["id"])]
        item["usage"] = {"tokens": usage.get(item["id"], {}).get("tokens", 0),
                         "invocations": usage.get(item["id"], {}).get("invocations", 0)}
        item["recent_success"] = success.get(item["id"], {}).get("success_rate")
        item["run_count"] = success.get(item["id"], {}).get("runs", 0)
    return discovered


def model_registry() -> ModelRegistry:
    return ModelRegistry.from_yaml(PACKAGE_ROOT / "config" / "models.yaml",
                                   platform_home() / "models.yaml")


def profiles() -> list[dict[str, Any]]:
    installed_skills = set(SkillRegistry.from_yaml(PACKAGE_ROOT / "config" / "default_skills.yaml").all())
    tools = {tool.id for tool in ToolRegistry.default().all()}
    evaluations = EvaluationRegistry()
    result = []
    for profile in profile_registry().all():
        data = profile.to_dict()
        data["installed_skills"] = sorted(set(profile.skills) & installed_skills)
        data["missing_skills"] = sorted(set(profile.skills) - installed_skills)
        data["available_tools"] = sorted(set(profile.tools) & tools)
        data["evaluation_strategies"] = [item.to_dict() for item in evaluations.resolve(profile.evaluation)]
        result.append(data)
    return result


def tools() -> list[dict[str, Any]]:
    return ToolRegistry.default().to_dict()
