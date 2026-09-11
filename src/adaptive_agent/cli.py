from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from adaptive_agent import __version__
from adaptive_agent.bootstrap import (
    analyze_project,
    consumption_mode,
    platform_config,
    provider_preference,
    set_provider_preference,
    set_consumption_mode,
    setup as run_setup,
)
from adaptive_agent.core.artifacts import Artifact, ArtifactStore, ArtifactType
from adaptive_agent.core.models import Task, new_id
from adaptive_agent.core.orchestrator import Orchestrator
from adaptive_agent.git.worktree import WorktreeManager
from adaptive_agent.intelligence.project import ProjectIntelligenceStore
from adaptive_agent.project.context_index import ProjectContextIndex
from adaptive_agent.project.adapter import (
    UAP_END,
    UAP_START,
    detach_project,
    initialize_project,
    orchestration_config,
    project_constraints,
    project_consumption_mode,
    project_profiles,
    project_provider_preference,
)
from adaptive_agent.project.discovery import discover
from adaptive_agent.providers.mock import MockProvider
from adaptive_agent.providers.registry import providers as provider_registry
from adaptive_agent.registry_view import (
    agents as registry_agents,
    model_registry,
    profiles as registry_profiles,
    providers as registry_providers,
    skills as registry_skills,
    tools as registry_tools,
)
from adaptive_agent.runtime import RESOURCE_ROOT, database, event_bus, platform_home


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="agentctl",
                                   description="Universal Agent Platform")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    for name, help_text in (("prepare", "retrieve context for the current AI task; zero provider calls"),
                            ("remember", "save a short source-linked fact for later tasks"),
                            ("check", "run allowlisted validation with compact output")):
        commands.add_parser(name, help=help_text)

    setup = commands.add_parser("setup", help="prepare the user-level platform installation")
    setup.add_argument("--auto", action="store_true", help="accept safe defaults for every decision")
    setup.add_argument("--non-interactive", action="store_true",
                       help="fail instead of guessing when a decision is required")
    setup.add_argument("--json", action="store_true")

    init = commands.add_parser("init", help="initialize a project adapter")
    init.add_argument("path", nargs="?", default=".")
    init.add_argument("--auto", action="store_true", help="detect and apply recommended work profiles")
    init.add_argument("--profiles", help="comma-separated work profile ids to activate")
    init.add_argument("--dry-run", action="store_true", help="report what would change and exit")
    init.add_argument("--force", action="store_true")
    init.add_argument("--upgrade", action="store_true", help="upgrade markers without replacing project content")
    init.add_argument("--json", action="store_true")

    attach = commands.add_parser("attach", help="attach the platform to an existing project")
    attach.add_argument("path", nargs="?", default=".")
    attach.add_argument("--profiles", help="comma-separated work profile ids to activate")
    attach.add_argument("--detach", action="store_true", help="hand orchestration back to the user")
    attach.add_argument("--json", action="store_true")

    run = commands.add_parser("run", help="plan and execute a goal")
    run.add_argument("goal")
    run.add_argument("--provider", default="auto", help="provider id, or 'auto' to let the router choose")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--timeout", type=float, default=900)
    run.add_argument("--in-place", action="store_true", help="allow a modifying run in the current worktree")
    run.add_argument("--profiles", help="override the project's active work profiles")
    run.add_argument("--approve", action="append", default=[], metavar="GATE",
                     help="authorize one approval gate for this run; repeatable")
    run.add_argument("--explain", action="store_true", help="print the composition rationale and exit")
    run.add_argument("--consumption", choices=("economy", "balanced", "maximum"),
                     help="override the project consumption policy for this run")

    orchestrate = commands.add_parser("orchestrate", help="canonical AI-assistant orchestration entrypoint")
    orchestrate.add_argument("goal")
    orchestrate.add_argument("--provider", default="auto")
    orchestrate.add_argument("--json", action="store_true", help="return bounded machine-readable output")
    orchestrate.add_argument("--timeout", type=float, default=900)
    orchestrate.add_argument("--in-place", action="store_true")
    orchestrate.add_argument("--profiles")
    orchestrate.add_argument("--approve", action="append", default=[], metavar="GATE")
    orchestrate.add_argument("--consumption", choices=("economy", "balanced", "maximum"),
                             help="override the project consumption policy for this run")

    status_command = commands.add_parser("status")
    status_command.add_argument("--json", action="store_true")
    status_command.add_argument("--debug", action="store_true",
                                help="include legacy and experimental lifecycle metrics")
    for name in ("warm-start", "resume"):
        warm = commands.add_parser(name, help="inspect reusable project intelligence before a run")
        warm.add_argument("goal", nargs="?", default="continue the current project work")
        warm.add_argument("--json", action="store_true")
    context = commands.add_parser("context", help="inspect layered project context")
    context.add_argument("--json", action="store_true")
    context_subcommands = context.add_subparsers(dest="context_command", required=False)
    context_explain = context_subcommands.add_parser("explain")
    context_explain.add_argument("goal", nargs="?", default="continue the current project work")
    context_explain.add_argument("--json", action="store_true")
    intelligence_command = commands.add_parser("intelligence", help="inspect learned project intelligence")
    intelligence_subcommands = intelligence_command.add_subparsers(dest="intelligence_command", required=True)
    intelligence_explain = intelligence_subcommands.add_parser("explain")
    intelligence_explain.add_argument("--json", action="store_true")
    agents_command = commands.add_parser("agents")
    agents_command.add_argument("--verbose", action="store_true")
    agents_command.add_argument("--json", action="store_true")
    agent_command = commands.add_parser("agent")
    agent_subcommands = agent_command.add_subparsers(dest="agent_command", required=True)
    agent_show = agent_subcommands.add_parser("show")
    agent_show.add_argument("name")

    skills_command = commands.add_parser("skills")
    skills_command.add_argument("--json", action="store_true")
    skill_command = commands.add_parser("skill")
    skill_subcommands = skill_command.add_subparsers(dest="skill_command", required=True)
    skill_show = skill_subcommands.add_parser("show")
    skill_show.add_argument("name")
    skill_explain = skill_subcommands.add_parser("explain")
    skill_explain.add_argument("name")
    skill_validate = skill_subcommands.add_parser("validate")
    skill_validate.add_argument("name")
    skill_history = skill_subcommands.add_parser("history")
    skill_history.add_argument("name")
    skill_candidates = skill_subcommands.add_parser("candidates")
    skill_candidates.add_argument("capability")

    tools_command = commands.add_parser("tools", help="list deterministic tools")
    tools_command.add_argument("--json", action="store_true")
    profiles_command = commands.add_parser("profiles", help="list installed work profiles")
    profiles_command.add_argument("--verbose", action="store_true")
    profiles_command.add_argument("--json", action="store_true")
    profile_command = commands.add_parser("profile")
    profile_subcommands = profile_command.add_subparsers(dest="profile_command", required=True)
    profile_show = profile_subcommands.add_parser("show")
    profile_show.add_argument("name")

    providers_command = commands.add_parser("providers", help="list AI providers and readiness")
    providers_command.add_argument("--verbose", action="store_true")
    providers_command.add_argument("--json", action="store_true")
    provider_command = commands.add_parser("provider")
    provider_subcommands = provider_command.add_subparsers(dest="provider_command", required=True)
    provider_prefer = provider_subcommands.add_parser("prefer")
    provider_prefer.add_argument("name", nargs="+")
    provider_subcommands.add_parser("show").add_argument("name")

    consumption = commands.add_parser("consumption", help="show or set the global quota policy")
    consumption.add_argument("mode", nargs="?", choices=("economy", "balanced", "maximum"))
    consumption.add_argument("--json", action="store_true")

    provider_test = commands.add_parser("provider-test", help="run one tiny read-only provider request")
    provider_test.add_argument("name")
    provider_test.add_argument("--timeout", type=float, default=30.0)
    provider_test.add_argument("--prompt", default="Return exactly: UAP_PROVIDER_OK")
    provider_test.add_argument("--json", action="store_true")

    demo = commands.add_parser("demo", help="offline deterministic cross-provider routing demo")
    demo.add_argument("--delay", type=float, default=0.0, help="accepted for compatibility; no provider executes")
    demo.add_argument("--json", action="store_true")

    models_command = commands.add_parser("models", help="list the model catalog")
    models_command.add_argument("--json", action="store_true")
    commands.add_parser("registry")
    for name in ("tasks", "runs", "doctor", "artifacts"):
        commands.add_parser(name)
    replay = commands.add_parser("replay", help="print a run event timeline")
    replay.add_argument("run_id")
    explain = commands.add_parser("explain", help="explain team, routing, and escalation for a run")
    explain.add_argument("run_id")
    return root


# -- helpers ---------------------------------------------------------------


def _project_id(db, path: Path) -> str | None:
    rows = db.query("SELECT id FROM projects WHERE path=?", (str(path.resolve()),))
    return rows[0]["id"] if rows else None


def _is_read_only(goal: str) -> bool:
    from adaptive_agent.core.goal_analyzer import GoalAnalyzer

    return GoalAnalyzer(profiles=None).analyze(goal).read_only


def requires_orchestration(goal: str) -> bool:
    """Conservative hint for integrations; ownership is still decided by project config."""
    from adaptive_agent.core.goal_analyzer import GoalAnalyzer
    from adaptive_agent.profiles.registry import profile_registry

    lowered = " ".join(goal.lower().split())
    conversational = ("what does", "explain ", "rename this label", "fix typo", "change this label")
    if any(lowered.startswith(value) for value in conversational):
        return False
    analysis = GoalAnalyzer(profiles=profile_registry()).analyze(goal)
    return bool(analysis.capabilities) and not analysis.inferred


def _resolve_provider(name: str) -> str:
    """Turn `auto` into a concrete, ready provider id."""
    registry = provider_registry()
    if name and name != "auto":
        return name
    for preferred in provider_preference():
        if preferred != "auto" and preferred in registry:
            return preferred
    ready = [item["id"] for item in registry.discover() if item["ready"] and item["id"] != "mock"]
    return ready[0] if ready else "mock"


def _provider(name: str, timeout: float = 900, delay: float = 0.02):
    registry = provider_registry()
    resolved = _resolve_provider(name)
    if resolved not in registry:
        raise ValueError(f"unknown provider: {resolved}. Run 'agentctl providers' to see the registered adapters.")
    descriptor = registry.get(resolved)
    if not descriptor.implemented:
        raise ValueError(f"{descriptor.display_name} is plugin-ready but has no execution adapter in this build.")
    return registry.create(resolved, timeout=timeout, delay=delay)


def _needs_isolation(goal: str, in_place: bool, workdir: Path) -> bool:
    """Git isolation is a strategy for write-heavy work in a repository, not a rule."""
    return not in_place and not _is_read_only(goal) and (workdir / ".git").exists()


def _prepare_worktree(goal: str, provider_name: str, run_id: str, in_place: bool) -> tuple[Path, str | None]:
    current = Path.cwd().resolve()
    if provider_name == "mock" or not _needs_isolation(goal, in_place, current):
        return current, None
    manager = WorktreeManager(current)
    if not manager.is_repository():
        return current, None
    worktree = manager.create(run_id)
    return worktree, str(worktree)


def _run_goal(goal: str, provider_name: str = "mock", delay: float = 0.02,
              timeout: float = 900, in_place: bool = False, entry_source: str = "cli",
              orchestration_owner: str = "universal-agent-platform", profiles: list[str] | None = None,
              approvals: list[str] | None = None,
              consumption: str | None = None) -> tuple[str, str, str | None]:
    db = database()
    run_id = new_id("RUN")
    resolved = _resolve_provider(provider_name)
    workdir, worktree = _prepare_worktree(goal, resolved, run_id, in_place)
    info = discover(workdir)
    project_id = _project_id(db, Path.cwd())
    orchestrator = _orchestrator(
        db, resolved, timeout, delay, profiles,
        provider_preference_override=[resolved] if provider_name != "auto" else None,
        consumption_override=consumption)
    try:
        completed_id = asyncio.run(orchestrator.run_goal(
            goal, project_id, str(workdir), run_id, info.name, info.type,
            orchestration_owner, entry_source, info.signals,
            project_constraints(Path.cwd()), approvals or []))
    except KeyboardInterrupt:
        print("Run cancelled safely.", file=sys.stderr)
        raise
    status = db.query("SELECT status FROM runs WHERE id=?", (completed_id,))[0]["status"]
    if worktree:
        ArtifactStore(db).save(Artifact(completed_id, ArtifactType.WORKSPACE, "Isolated Git worktree",
                                        worktree, kind="git_worktree", metadata={"integrated": False}))
    return completed_id, status, worktree


def _orchestrator(db, provider_name: str, timeout: float = 900, delay: float = 0.02,
                  profiles: list[str] | None = None, provider=None,
                  provider_preference_override: list[str] | None = None,
                  consumption_override: str | None = None) -> Orchestrator:
    cwd = Path.cwd()
    preference = provider_preference_override or project_provider_preference(cwd)
    if provider_preference_override is None and preference == ["auto"]:
        preference = provider_preference()
    return Orchestrator(db, provider or _provider(provider_name, timeout, delay), event_bus(db),
                        provider_name=provider_name,
                        provider_preference=preference,
                        active_profiles=profiles if profiles is not None else project_profiles(cwd),
                        consumption_mode=(consumption_override or project_consumption_mode(cwd)
                                          or consumption_mode()))


def _dry_run(goal: str, provider_name: str, profiles: list[str] | None = None,
             consumption: str | None = None) -> dict:
    db = database()
    info = discover(Path.cwd())
    resolved = _resolve_provider(provider_name)
    # Dry-run spawns no external process; the provider name only shapes routing.
    orchestrator = _orchestrator(
        db, resolved, profiles=profiles, provider=MockProvider(delay=0),
        provider_preference_override=[resolved] if provider_name != "auto" else None,
        consumption_override=consumption)
    composition = orchestrator.plan("RUN-DRYRUN", goal, working_directory=str(Path.cwd()),
                                    project_name=info.name, project_type=info.type,
                                    project_signals=info.signals,
                                    constraints=project_constraints(Path.cwd()))
    graph = composition.graph
    return {
        "dry_run": True,
        "mode": composition.mode,
        "provider": resolved,
        "consumption": composition.consumption,
        "project": {"name": info.name, "type": info.type, "path": str(Path.cwd()),
                    "recommended_profiles": info.recommended_profiles},
        "analysis": composition.analysis.to_dict(),
        "execution_plan": composition.execution_plan.to_dict() if composition.execution_plan else {},
        "project_intelligence": composition.project_intelligence,
        "team": composition.team.to_dict(),
        "required_capabilities": sorted({capability for task in graph.tasks.values()
                                         for capability in task.required_capabilities}),
        "tasks": [{"id": task.id, "title": task.title, "kind": task.kind.value,
                   "dependencies": task.dependencies, "agent": task.owner,
                   "provider": task.metadata.get("provider"), "model": task.metadata.get("model"),
                   "reasoning": task.reasoning, "artifact_type": task.artifact_type,
                   "provider_profile": task.metadata.get("provider_profile"),
                   "reason": task.metadata.get("routing_reason", "")} for task in graph.tasks.values()],
    }


def _run_summary(db, run_id: str, worktree: str | None = None) -> dict:
    run = db.query("SELECT * FROM runs WHERE id=?", (run_id,))[0]
    tasks = db.query("SELECT id,owner,status,kind,data_json FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,))
    usage = db.query("SELECT agent,SUM(input_tokens) input,SUM(output_tokens) output,SUM(cached_tokens) cached,"
                     "SUM(invocation_count) invocations,token_source,provider FROM token_usage "
                     "WHERE run_id=? GROUP BY agent,token_source,provider", (run_id,))
    events = db.query("SELECT event FROM events WHERE run_id=?", (run_id,))
    receipts = db.query("SELECT data_json FROM receipts WHERE task_id IN (SELECT id FROM tasks WHERE run_id=?)", (run_id,))
    composition = db.loads(run.get("composition_json"))
    evaluative = {item["role_id"] for item in composition.get("team", {}).get("members", [])
                  if item.get("evaluative")}
    reported_files, reviews = set(), []
    for row in receipts:
        data = json.loads(row["data_json"])
        reported_files.update(data.get("files", []))
        if data.get("agent") in evaluative or data.get("agent") == "reviewer":
            reviews.append(data.get("status"))
    warnings = []
    for task in tasks:
        warnings.extend(json.loads(task["data_json"]).get("metadata", {}).get("efficiency_warnings", []))
    execution_path = worktree
    if not execution_path and tasks:
        execution_path = json.loads(tasks[0]["data_json"]).get("metadata", {}).get("working_directory")
    changed_files = []
    if execution_path and (Path(execution_path) / ".git").exists():
        status = subprocess.run(["git", "-C", execution_path, "status", "--porcelain"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        changed_files = [line[3:].strip() for line in status.stdout.splitlines() if len(line) > 3]
    artifacts = ArtifactStore(db).for_run(run_id)
    completed = sum(item["status"] == "completed" for item in tasks)
    return {"run_id": run_id, "status": run["status"], "goal": run["goal"], "result": run["status"],
            "result_summary": f"{completed} of {len(tasks)} tasks completed",
            "orchestration_owner": run.get("orchestration_owner", "universal-agent-platform"),
            "entry_source": run.get("entry_source", "cli"),
            "work_profiles": [item for item in str(run.get("work_profiles", "")).split(",") if item],
            "consumption": composition.get("consumption", {}),
            "team": composition.get("team", {}).get("rationale", []),
            "tasks": f"{completed} / {len(tasks)} completed",
            "agents": [{"agent": item["owner"], "status": item["status"], "kind": item.get("kind", "agent"),
                        "model": json.loads(item["data_json"]).get("metadata", {}).get("model")} for item in tasks],
            "tokens": usage, "escalations": sum(item["event"] == "task_escalating" for item in events),
            "ai_invocations": sum(int(item.get("invocations") or 0) for item in usage),
            "deterministic_operations": sum(item.get("kind") == "tool" for item in tasks),
            "approvals_pending": [item["owner"] for item in tasks
                                  if item.get("kind") == "approval" and item["status"] != "completed"],
            "files_changed": sorted(changed_files), "files_reported": sorted(reported_files),
            "review": "PASS" if reviews and all(value == "completed" for value in reviews) else "N/A",
            "efficiency": warnings or "No efficiency warnings.", "worktree": worktree,
            "worktrees": [item["location"] for item in artifacts if item["kind"] == "git_worktree"],
            "artifacts": [{"path": item["location"], "kind": item["kind"], "type": item["type"],
                           "name": item["name"]} for item in artifacts],
            "project_intelligence": composition.get("project_intelligence", {}),
            "token_usage": usage}


def _project_status(db, path: Path, debug: bool = False) -> str:
    config = orchestration_config(path)
    agents_path = path / "AGENTS.md"
    instructions = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    marker = UAP_START in instructions and UAP_END in instructions
    latest = db.query("SELECT id,status,entry_source,work_profiles FROM runs ORDER BY created_at DESC LIMIT 1")
    active = project_profiles(path) or ["(inferred from each goal)"]
    ready = [item["name"] for item in registry_providers(db) if item["ready"]]
    context = ProjectContextIndex(path).status() if (path / ".agent").is_dir() else None
    architecture = (" + ".join(context["architecture"].values())
                    if context and context["architecture"] else "unknown")
    lines = [f"PROJECT\n{path.name}", "", f"Architecture:\n{architecture}", "",
             (f"Index:\n{context['size_bytes'] / 1024:.1f} KB" if context else "Index:\nunavailable"),
             "", (f"Cached relevant files:\n{context['cached_relevant_files']}" if context
                    else "Cached relevant files:\n0"),
             "", f"Skills:\n{len(list((path / '.agent' / 'skills').glob('*/skill.json'))) if (path / '.agent' / 'skills').exists() else 0}",
             "", f"Last task:\n{latest[0]['status'].upper() if latest else 'none'}"]
    if debug:
        intelligence = ProjectIntelligenceStore(path).status() if (path / ".agent").is_dir() else None
        lines += ["", "DEBUG", f"Active work profiles: {', '.join(active)}",
                  f"Consumption policy: {project_consumption_mode(path) or consumption_mode()}",
                  f"Ready providers: {', '.join(ready) or 'none'}",
                  f"Legacy intelligence: {json.dumps(intelligence) if intelligence else 'unavailable'}",
                  "Child execution guard: READY",
                  f"Router authority: {'platform' if config['owner'] == 'universal-agent-platform' else config['owner']}"]
    return "\n".join(lines)


def _table(headers: list[str], values: list[list[object]]) -> str:
    rows = [[str(value if value is not None else "-") for value in row] for row in values]
    widths = [max(len(header), *(len(row[index]) for row in rows)) if rows else len(header)
              for index, header in enumerate(headers)]
    lines = ["  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)),
             "  ".join("-" * width for width in widths)]
    lines.extend("  ".join(value.ljust(widths[index]) for index, value in enumerate(row)) for row in rows)
    return "\n".join(lines)


def _doctor(db) -> str:
    from adaptive_agent.profiles.registry import profile_registry

    measured = bool(db.query("SELECT 1 FROM token_usage WHERE token_source='measured' LIMIT 1"))
    git_ok = subprocess.run(["git", "--version"], capture_output=True, check=False).returncode == 0
    repo_ok = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], capture_output=True, check=False).returncode == 0
    config = orchestration_config(Path.cwd())
    agents_path = Path.cwd() / "AGENTS.md"
    instructions = agents_path.read_text(encoding="utf-8") if agents_path.exists() else ""
    marker = UAP_START in instructions and UAP_END in instructions
    yes = lambda value: "PASS" if value else "UNAVAILABLE"
    discovered = registry_providers(db)
    models = model_registry()
    registry = profile_registry()

    lines = [f"Universal Agent Platform v{__version__}", "",
             "Platform", "--------",
             f"Python             PASS ({sys.version.split()[0]})",
             f"SQLite             {yes(os.access(db.path.parent, os.W_OK))}",
             f"Platform home      {yes(platform_home().exists())} ({platform_home()})",
             f"Git                {yes(git_ok)}",
             f"Work profiles      PASS ({len(registry.all())} installed)",
             f"Model catalog      PASS ({len(models.all())} models)",
             f"Measured usage     {yes(measured)} (requires a real provider run)",
             "", "Providers", "---------"]
    width = max(len(item["name"]) for item in discovered) + 2
    for item in discovered:
        label = "READY" if item["ready"] else item["status"].upper()
        lines.append(f"{item['name']:<{width}}{label:<14}{item['type'].upper():<8}{item['detail']}")
    lines += ["", "Project", "-------",
              f"Git repository     {yes(repo_ok)}",
              f".agent adapter     {yes((Path.cwd() / '.agent').is_dir())}",
              f"Universal orchestration {yes(config['owner'] == 'universal-agent-platform')}",
              f"Project marker     {yes(marker)}",
              f"Active profiles    {', '.join(project_profiles(Path.cwd())) or 'inferred per goal'}",
              f"Consumption       {project_consumption_mode(Path.cwd()) or consumption_mode()}",
              f"Approval gates     {', '.join(project_constraints(Path.cwd())) or 'none configured'}",
              "Recursion protection PASS",
              f"Router authority   {'platform' if config['owner'] == 'universal-agent-platform' else config['owner']}",
              "", "API", "---", "FastAPI            PASS (library interface; no bundled web UI)"]
    return "\n".join(lines)


def _explain(db, run_id: str) -> dict:
    run = db.query("SELECT * FROM runs WHERE id=?", (run_id,))
    composition = db.loads(run[0].get("composition_json")) if run else {}
    tasks = db.query("SELECT id,title,kind,data_json FROM tasks WHERE run_id=? ORDER BY rowid", (run_id,))
    escalations = db.query("SELECT timestamp,task_id,metadata_json FROM events WHERE run_id=? "
                           "AND event='task_escalating' ORDER BY timestamp", (run_id,))
    team = composition.get("team", {})
    analysis = composition.get("analysis", {})
    execution_plan = composition.get("execution_plan", {})
    run_skills = db.query(
        "SELECT task_id,skill_id,version,loaded_references_json,context_tokens "
        "FROM run_skills WHERE run_id=? ORDER BY created_at", (run_id,))
    for item in run_skills:
        item["loaded_references"] = json.loads(item.pop("loaded_references_json"))
    return {
        "run_id": run_id,
        "mode": composition.get("mode", "unknown"),
        "consumption": composition.get("consumption", {}),
        "execution_strategy": execution_plan,
        "skills_used": run_skills,
        "project_intelligence": composition.get("project_intelligence", {}),
        "why_this_team": {
            "goal_requires": analysis.get("capabilities", []),
            "complexity": analysis.get("complexity"),
            "risk": analysis.get("risk"),
            "active_profiles": analysis.get("profiles", []),
            "selected": [{"role": item["name"], "responsibility": item["responsibility"],
                          "because": item["reason"], "profile": item["profile"],
                          "origin": item["origin"]} for item in team.get("members", [])],
            "omitted": team.get("omitted", []),
            "rationale": team.get("rationale", []),
            "capability_resolution": team.get("resolutions", []),
            "evidence": analysis.get("evidence", []),
        },
        "why_this_provider": [
            {"task_id": row["id"], "title": row["title"], "kind": row["kind"],
             **{key: value for key, value in json.loads(row["data_json"]).get("metadata", {})
                .get("routing", {}).items() if key != "candidates"},
             "considered": [item["model"] for item in json.loads(row["data_json"])
                            .get("metadata", {}).get("routing", {}).get("candidates", [])]}
            for row in tasks],
        "escalations": [{**row, "metadata": json.loads(row.pop("metadata_json"))} for row in escalations],
    }


# -- entry point -----------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] in {"prepare", "remember", "check"}:
        from adaptive_agent.project.direct import main as direct_main
        return direct_main(arguments)
    args = parser().parse_args(argv)
    db = database()
    selected_profiles = ([item.strip() for item in args.profiles.split(",") if item.strip()]
                         if getattr(args, "profiles", None) else None)

    if args.command == "setup":
        result = run_setup(auto=args.auto, non_interactive=args.non_interactive)
        print(json.dumps(result.to_dict(), indent=2) if args.json else result.render())
        return 0 if result.ok else 2

    if args.command == "init":
        path = Path(args.path).resolve()
        plan = analyze_project(path)
        if args.dry_run:
            print(json.dumps(plan.to_dict(), indent=2) if args.json else plan.render())
            return 0
        try:
            info = initialize_project(path, RESOURCE_ROOT / "templates", args.force, args.upgrade,
                                      selected_profiles, args.auto)
        except FileExistsError as error:
            print(f"{error}. Use --upgrade to refresh markers or --force to overwrite.", file=sys.stderr)
            return 2
        project_id = _project_id(db, path) or new_id("PRJ")
        db.execute("INSERT OR REPLACE INTO projects(id,path,name,type,config_json) VALUES(?,?,?,?,?)",
                   (project_id, str(path), info.name, info.type,
                    db.json({"languages": info.languages, "profiles": project_profiles(path),
                             "signals": info.signals})))
        payload = {"path": str(path), "type": info.type, "languages": info.languages,
                   "profiles": project_profiles(path), "recommended": info.recommended_profiles}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(plan.render(pending=False))
            print(f"\nProject initialized: {path}")
            print(f"Active work profiles: {', '.join(payload['profiles']) or 'inferred per goal'}")
            print('\nSuggested next step:\n  agentctl run "<your goal>" --dry-run')
            print('\nOr tell your preferred AI assistant:\n  Use the Universal Agent Platform for this project.')
        return 0

    if args.command == "attach":
        path = Path(args.path).resolve()
        if args.detach:
            changed = detach_project(path)
            print(json.dumps({"detached": changed}, indent=2) if args.json
                  else "Detached. Orchestration returned to the user:\n" + "\n".join(f"  {c}" for c in changed))
            return 0
        info = initialize_project(path, RESOURCE_ROOT / "templates", force=False, upgrade=True,
                                  profiles=selected_profiles, auto=selected_profiles is None)
        payload = {"path": str(path), "profiles": project_profiles(path), "type": info.type}
        print(json.dumps(payload, indent=2) if args.json
              else f"Attached to {path}\nActive work profiles: {', '.join(payload['profiles']) or 'inferred per goal'}")
        return 0

    if args.command == "orchestrate":
        if os.getenv("UAP_CHILD_EXECUTION") == "1":
            print("Recursion blocked: child executions may not orchestrate.", file=sys.stderr)
            return 3
        config = orchestration_config(Path.cwd())
        if config["owner"] != "universal-agent-platform":
            print("Current project does not declare platform orchestration. Run agentctl init --auto.", file=sys.stderr)
            return 2
        try:
            run_id, status, worktree = _run_goal(args.goal, args.provider, timeout=args.timeout,
                                                 in_place=args.in_place, entry_source="codex_parent",
                                                 profiles=selected_profiles, approvals=args.approve,
                                                 consumption=args.consumption)
        except (RuntimeError, ValueError) as error:
            print(f"Run preparation failed: {error}", file=sys.stderr)
            return 2
        summary = _run_summary(db, run_id, worktree)
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Adaptive Agent run {summary['status']}: {run_id}\n{summary['result_summary']}")
        return 0 if status == "completed" else 1

    if args.command == "run":
        if args.dry_run or args.explain:
            print(json.dumps(_dry_run(args.goal, args.provider, selected_profiles,
                                      args.consumption), indent=2))
            return 0
        try:
            run_id, status, worktree = _run_goal(args.goal, args.provider, timeout=args.timeout,
                                                 in_place=args.in_place, profiles=selected_profiles,
                                                 approvals=args.approve,
                                                 consumption=args.consumption)
        except (RuntimeError, ValueError) as error:
            print(f"Run preparation failed: {error}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            return 130
        print(json.dumps(_run_summary(db, run_id, worktree), indent=2))
        return 0 if status == "completed" else 1

    if args.command == "status":
        context_status = (ProjectContextIndex(Path.cwd()).status()
                          if (Path.cwd() / ".agent").is_dir() else None)
        intelligence = (ProjectIntelligenceStore(Path.cwd()).status()
                        if args.debug and (Path.cwd() / ".agent").is_dir() else None)
        if args.json:
            print(json.dumps({"project": orchestration_config(Path.cwd()),
                              "profiles": project_profiles(Path.cwd()),
                              "consumption": project_consumption_mode(Path.cwd()) or consumption_mode(),
                              "providers_ready": provider_registry().ready_ids(),
                              "context": context_status,
                              **({"project_intelligence": intelligence} if args.debug else {})}, indent=2))
        else:
            print(_project_status(db, Path.cwd(), debug=args.debug))
    elif args.command in {"warm-start", "resume"}:
        selection = ProjectContextIndex(Path.cwd()).select(args.goal)
        payload = {"goal": args.goal, **selection.to_dict()}
        print(json.dumps(payload, indent=2) if args.json else
              f"FRESH SESSION CONTEXT\nRelevant paths: {', '.join(selection.relevant_paths) or 'none'}\n"
              f"Cached files: {len(selection.cached_files)}\n"
              f"Estimated context: {selection.estimated_tokens} tokens")
    elif args.command == "context":
        goal = getattr(args, "goal", None) or "continue the current project work"
        selection = ProjectContextIndex(Path.cwd()).select(goal)
        payload = selection.to_dict()
        print(json.dumps(payload, indent=2) if args.json else
              f"Project index: {selection.context_chars} chars\n"
              f"Relevant paths:\n" +
              "\n".join(f"- {item}" for item in selection.relevant_paths))
    elif args.command == "intelligence" and args.intelligence_command == "explain":
        explanation = ProjectIntelligenceStore(Path.cwd()).explain()
        if args.json:
            print(json.dumps(explanation, indent=2))
        else:
            status = explanation["status"]
            print(f"Project intelligence: LEVEL_{status['level']}_{status['level_name'].upper()}")
            for item in explanation["items"]:
                print(f"- {item['id']} [{item['kind']}]: {item['summary']}")
                print(f"  persisted because: {item.get('why_persisted') or 'not recorded'}; "
                      f"reuse: {item.get('validated_reuse_count', 0)} validated; payback: {item['payback_status']}")
    elif args.command == "agents":
        values = registry_agents(db)
        if args.verbose or args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["NAME", "TYPE", "STATUS", "WORK PROFILE", "PROVIDER", "MODEL"],
                         [[item["name"], item["type"].upper(), item["status"].upper(),
                           item["work_profile"], item["provider"], item["model"]] for item in values]))
    elif args.command == "agent":
        item = next((value for value in registry_agents(db)
                     if value["id"] == args.name or value["name"].lower() == args.name.lower()), None)
        if not item:
            print(f"Agent not found: {args.name}", file=sys.stderr)
            return 2
        print(json.dumps(item, indent=2))
    elif args.command == "skills":
        values = registry_skills(db)
        if args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["NAME", "SCOPE", "LOADED", "USED BY"],
                     [[item["name"], item["scope"].upper(), "yes" if item["loaded"] else "no",
                       ", ".join(item["used_by_agents"]) or "none"] for item in values]))
    elif args.command == "skill":
        from adaptive_agent.skills.manifest import SkillTrust
        from adaptive_agent.skills.quality import SkillQualityStore
        from adaptive_agent.skills.registry import SkillRegistry
        from adaptive_agent.skills.resolver import SkillResolver

        skill_registry = SkillRegistry.from_yaml(RESOURCE_ROOT / "config" / "default_skills.yaml")
        skill_registry.discover_directory(RESOURCE_ROOT / "skills", SkillTrust.BUILT_IN)
        skill_registry.discover_directory(platform_home() / "skills", SkillTrust.TRUSTED)
        skill_registry.discover_directory(Path.cwd() / ".agent" / "skills", SkillTrust.PROJECT_LOCAL)
        if args.skill_command == "candidates":
            candidates = SkillResolver(skill_registry.manifests()).candidates(
                [args.capability], minimize_cost=(project_consumption_mode(Path.cwd())
                                                  or consumption_mode()) == "economy")
            print(json.dumps([item.to_dict() for item in candidates], indent=2))
            return 0
        name = args.name
        if name not in {item.id for item in skill_registry.manifests()}:
            print(f"Skill not found: {name}", file=sys.stderr)
            return 2
        if args.skill_command == "show":
            manifest = skill_registry.manifest(name)
            loaded = skill_registry.load_selected(name)
            payload = {"manifest": manifest.to_dict(), "instructions": loaded.instructions,
                       "available_references": manifest.references,
                       "loaded_references": [], "context_tokens": loaded.estimated_context_tokens}
        elif args.skill_command == "validate":
            payload = skill_registry.validate(name)
        elif args.skill_command == "history":
            payload = {"quality": SkillQualityStore(db).get(name).to_dict(),
                       "runs": db.query("SELECT * FROM skill_runs WHERE skill_id=? ORDER BY created_at DESC",
                                        (name,))}
        else:
            manifest = skill_registry.manifest(name)
            candidates = SkillResolver(skill_registry.manifests()).candidates(manifest.capabilities)
            payload = {"skill": name, "capabilities": manifest.capabilities,
                       "selection": next((item.to_dict() for item in candidates
                                          if item.manifest.id == name), None),
                       "ranked_alternatives": [item.to_dict() for item in candidates
                                               if item.manifest.id != name]}
        print(json.dumps(payload, indent=2))
    elif args.command == "tools":
        values = registry_tools()
        if args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["TOOL", "RISK", "EXECUTION", "CAPABILITIES"],
                     [[item["name"], item["risk"].upper(), item["execution"],
                       ", ".join(item["capabilities"])] for item in values]))
    elif args.command == "profiles":
        values = registry_profiles()
        if args.verbose or args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["PROFILE", "ROLES", "CAPABILITIES", "EVALUATION", "TRUST"],
                         [[item["id"], str(len(item["roles"])), str(len(item["capabilities"])),
                           ", ".join(item["evaluation"][:3]) or "none", item["trust"]] for item in values]))
    elif args.command == "profile":
        item = next((value for value in registry_profiles() if value["id"] == args.name), None)
        if not item:
            print(f"Profile not found: {args.name}. Run 'agentctl profiles'.", file=sys.stderr)
            return 2
        print(json.dumps(item, indent=2))
    elif args.command == "providers":
        values = registry_providers(db)
        if args.verbose or args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["PROVIDER", "STATUS", "TYPE", "EXECUTION", "MODELS", "DETAIL"],
                         [[item["name"], "READY" if item["ready"] else item["status"].upper(),
                           item["type"].upper(), item["execution_mode"],
                           str(len(item["models"])), item["detail"]]
                          for item in values]))
    elif args.command == "provider":
        if args.provider_command == "prefer":
            preferred = set_provider_preference(*args.name)
            print(f"Provider preference: {', '.join(preferred)}")
        else:
            item = next((value for value in registry_providers(db) if value["id"] == args.name), None)
            if not item:
                print(f"Provider not found: {args.name}", file=sys.stderr)
                return 2
            print(json.dumps(item, indent=2))
    elif args.command == "provider-test":
        if args.name not in provider_registry():
            print(f"Provider not found: {args.name}", file=sys.stderr)
            return 2
        provider = provider_registry().create(args.name, timeout=args.timeout)
        probe = provider.probe()
        if not probe.ready:
            payload = {"provider": args.name, "status": probe.state.value,
                       "detail": probe.detail, "executed": False}
            print(json.dumps(payload, indent=2) if args.json else
                  f"{args.name}: {probe.state.value.upper()} - {probe.detail}")
            return 2
        # Never expose the caller's current project merely to run a tiny
        # provider health request. Agentic CLI providers receive an empty,
        # isolated workspace; API reasoning providers simply ignore it.
        with tempfile.TemporaryDirectory(prefix="uap-provider-test-") as directory:
            task = Task(new_id("TASK"), new_id("RUN"), args.prompt,
                        "provider_test", ["text"], metadata={
                            "goal": args.prompt, "read_only": True,
                            "working_directory": directory,
                            "model": "env:UAP_OPENAI_COMPATIBLE_MODEL" if args.name == "openai_compatible" else None,
                        })
            receipt = asyncio.run(provider.execute(task))
        payload = {"provider": args.name, "status": receipt.status,
                   "output": receipt.summary, "model": receipt.model,
                   "duration_seconds": receipt.duration_seconds,
                   "usage": receipt.token_usage, "error": receipt.error_code}
        print(json.dumps(payload, indent=2) if args.json else
              f"{args.name}: {receipt.status.upper()} ({receipt.duration_seconds:.2f}s)\n{receipt.summary}")
        return 0 if receipt.status == "completed" else 1
    elif args.command == "consumption":
        selected = set_consumption_mode(args.mode) if args.mode else consumption_mode()
        from adaptive_agent.core.consumption import consumption_policy

        payload = consumption_policy(selected).to_dict()
        print(json.dumps(payload, indent=2) if args.json else
              f"Consumption policy: {selected}\n"
              f"Parallel agents: {payload['max_parallel_agents']}\n"
              f"Escalations per task: {payload['max_escalations_per_task']}\n"
              f"Context receipts: {payload['max_context_receipts']}")
        return 0
    elif args.command == "demo":
        from adaptive_agent.core.cross_provider_demo import cross_provider_demo

        payload = cross_provider_demo()
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print("Offline cross-provider routing demo (zero quota)\n")
            for role, decision in payload["routes"].items():
                print(f"{role}: {decision['provider']} / {decision['model']}")
                for reason in decision["reasons"]:
                    print(f"  - {reason}")
        return 0
    elif args.command == "models":
        values = model_registry().to_dict()
        if args.json:
            print(json.dumps(values, indent=2))
        else:
            print(_table(["MODEL", "PROVIDER", "TIER", "COST", "LATENCY", "TOP CAPABILITIES"],
                     [[item["id"], item["provider"], item["tier"], item["cost"], item["latency"],
                       ", ".join(sorted(name for name, level in item["capabilities"].items()
                                        if level in {"high", "very_high"})[:4]) or "-"]
                      for item in values]))
    elif args.command == "registry":
        print(json.dumps({"orchestration": orchestration_config(Path.cwd()),
                          "platform": platform_config(),
                          "agents": registry_agents(db), "skills": registry_skills(db),
                          "tools": registry_tools(), "profiles": registry_profiles(),
                          "providers": registry_providers(db), "models": model_registry().to_dict()}, indent=2))
    elif args.command == "tasks":
        print(json.dumps(db.query("SELECT id,run_id,title,owner,kind,status FROM tasks ORDER BY rowid DESC LIMIT 100"), indent=2))
    elif args.command == "runs":
        print(json.dumps(db.query("SELECT id,project_id,goal,status,created_at,completed_at,"
                                  "orchestration_owner,entry_source,work_profiles FROM runs "
                                  "ORDER BY created_at DESC LIMIT 100"), indent=2))
    elif args.command == "artifacts":
        print(json.dumps(db.query("SELECT id,run_id,task_id,path,kind,artifact_type FROM artifacts "
                                  "ORDER BY rowid DESC LIMIT 200"), indent=2))
    elif args.command == "replay":
        print(json.dumps(db.query("SELECT timestamp,event,agent,task_id,metadata_json FROM events "
                                  "WHERE run_id=? ORDER BY timestamp", (args.run_id,)), indent=2))
    elif args.command == "explain":
        print(json.dumps(_explain(db, args.run_id), indent=2))
    elif args.command == "doctor":
        print(_doctor(db))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
