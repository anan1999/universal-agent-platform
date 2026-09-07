from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import yaml

from adaptive_agent.project.discovery import ProjectInfo, discover


UAP_START = "<!-- UAP:START -->"
UAP_END = "<!-- UAP:END -->"
UAP_AGENTS_BLOCK = f"""{UAP_START}
# Universal Agent Platform

This repository uses the Universal Agent Platform as its task orchestrator.
For non-trivial project tasks, route the concise user goal and essential constraints through
`agentctl orchestrate \"<goal>\" --json`. The platform owns goal analysis, capability
resolution, team composition, the task DAG, provider and model routing, skills, tools,
evaluation, and escalation.

AI providers are bounded execution backends beneath the platform, never the orchestrator.
Do not run a second top-level planner while this platform owns orchestration.
An `UAP_CHILD_EXECUTION=1` process is a bounded executor and must never invoke the platform again.
Trivial conversation, explanation-only requests, and explicit user bypass requests may run directly.
{UAP_END}"""

DEFAULT_ORCHESTRATION = {"owner": "universal-agent-platform", "threshold": "non_trivial"}


def orchestration_config(path: Path) -> dict:
    data = project_config(path)
    if not data:
        return {"owner": "manual", "threshold": "non_trivial"}
    orchestration = data.get("orchestration", {}) or {}
    return {"owner": orchestration.get("owner", "manual"),
            "threshold": orchestration.get("threshold", "non_trivial")}


def project_config(path: Path) -> dict[str, Any]:
    config_path = Path(path).resolve() / ".agent" / "project.yaml"
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def project_profiles(path: Path) -> list[str]:
    """Work Profiles this project activates. Empty means "infer from the goal"."""
    return [str(item) for item in (project_config(path).get("profiles") or [])]


def project_constraints(path: Path) -> list[str]:
    constraints = (project_config(path).get("constraints") or {})
    return [str(item) for item in constraints.get("require_human_approval_for", [])]


def project_provider_preference(path: Path) -> list[str]:
    preference = ((project_config(path).get("providers") or {}).get("preference") or [])
    return [str(item) for item in preference] or ["auto"]


def update_agents_marker(path: Path) -> None:
    target = Path(path).resolve() / "AGENTS.md"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if UAP_START in existing and UAP_END in existing:
        before, remainder = existing.split(UAP_START, 1)
        _, after = remainder.split(UAP_END, 1)
        content = before.rstrip() + "\n\n" + UAP_AGENTS_BLOCK + after
    else:
        content = existing.rstrip() + ("\n\n" if existing.strip() else "") + UAP_AGENTS_BLOCK + "\n"
    target.write_text(content, encoding="utf-8")


def initialize_project(path: Path, templates: Path, force: bool = False, upgrade: bool = False,
                       profiles: Sequence[str] | None = None, auto: bool = False) -> ProjectInfo:
    """Write the project adapter. Never overwrites project content the user owns."""
    path = path.resolve()
    agent_dir = path / ".agent"
    info = discover(path)
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "knowledge").mkdir(exist_ok=True)

    project_path = agent_dir / "project.yaml"
    project = yaml.safe_load(project_path.read_text(encoding="utf-8")) if project_path.exists() else {}
    project = project or {}
    project["project"] = {**project.get("project", {}), "name": info.name, "type": info.type}
    project["languages"] = info.languages

    selected = list(profiles) if profiles else project.get("profiles") or info.recommended_profiles
    project["profiles"] = sorted(dict.fromkeys(selected))
    project["orchestration"] = {**DEFAULT_ORCHESTRATION, **project.get("orchestration", {}),
                                "owner": "universal-agent-platform"}
    project["providers"] = project.get("providers") or {"preference": ["auto"]}
    project["constraints"] = project.get("constraints") or {
        "require_human_approval_for": ["destructive_actions", "deployment", "publishing"]}
    project_path.write_text(yaml.safe_dump(project, sort_keys=False), encoding="utf-8")

    commands = {"commands": {}}
    if info.build_command:
        commands["commands"]["build"] = {"command": info.build_command, "timeout": 1200}
    if info.test_command:
        commands["commands"]["test"] = {"command": info.test_command, "timeout": 1200}
    commands_path = agent_dir / "commands.yaml"
    if not commands_path.exists():
        commands_path.write_text(yaml.safe_dump(commands, sort_keys=False), encoding="utf-8")

    capabilities_path = agent_dir / "capabilities.yaml"
    if not capabilities_path.exists():
        template = templates / "capabilities.yaml"
        capabilities_path.write_text(
            template.read_text(encoding="utf-8") if template.exists()
            else "capabilities:\n  required: []\n  optional: []\n  missing: []\n",
            encoding="utf-8")
    update_agents_marker(path)
    return info


def detach_project(path: Path) -> list[str]:
    """Remove the platform's marker from AGENTS.md. Leaves `.agent/` data intact."""
    path = Path(path).resolve()
    removed = []
    target = path / "AGENTS.md"
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if UAP_START in existing and UAP_END in existing:
            before, remainder = existing.split(UAP_START, 1)
            _, after = remainder.split(UAP_END, 1)
            target.write_text((before.rstrip() + "\n" + after.lstrip()).strip() + "\n", encoding="utf-8")
            removed.append(str(target))
    config_path = path / ".agent" / "project.yaml"
    if config_path.exists():
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        data["orchestration"] = {**data.get("orchestration", {}), "owner": "manual"}
        config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        removed.append(str(config_path))
    return removed


def approved_command(path: Path, name: str) -> dict:
    data = yaml.safe_load((path / ".agent" / "commands.yaml").read_text(encoding="utf-8")) or {}
    commands = data.get("commands", {})
    if name not in commands:
        raise PermissionError(f"command is not allowlisted: {name}")
    return commands[name]
