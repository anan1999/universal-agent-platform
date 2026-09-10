from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.capabilities import Requirement
from adaptive_agent.core.capability_resolver import CapabilityResolver
from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.consumption import ConsumptionPolicy, consumption_policy
from adaptive_agent.core.evaluation import EvaluationKind, EvaluationRegistry
from adaptive_agent.core.execution_planner import ExecutionPlan, ExecutionPlanner, ExecutionStrategy
from adaptive_agent.core.goal_analyzer import GoalAnalysis, GoalAnalyzer
from adaptive_agent.core.models import Event, TaskKind, new_id, now_iso
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.core.team_composer import TeamComposer, TeamMember, TeamPlan
from adaptive_agent.core.team_manager import TeamManager
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.core.universal_planner import UniversalPlanner
from adaptive_agent.models.registry import ModelRegistry
from adaptive_agent.intelligence.project import ContextSelection, ProjectIntelligenceStore
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.profiles.registry import WorkProfileRegistry, profile_registry
from adaptive_agent.providers.base import AIProvider
from adaptive_agent.providers.registry import ProviderRegistry, providers as provider_registry
from adaptive_agent.runtime import RESOURCE_ROOT, platform_home
from adaptive_agent.skills.manifest import SkillTrust
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.skills.resolver import SkillResolver
from adaptive_agent.storage.database import Database
from adaptive_agent.tasks.graph import TaskGraph


@dataclass(slots=True)
class Composition:
    """Everything the platform decided before executing anything."""

    analysis: GoalAnalysis
    team: TeamPlan
    graph: TaskGraph
    provider_rationale: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "universal"
    consumption: dict[str, Any] = field(default_factory=dict)
    execution_plan: ExecutionPlan | None = None
    project_intelligence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "analysis": self.analysis.to_dict(),
                "team": self.team.to_dict(), "provider_rationale": list(self.provider_rationale),
                "consumption": dict(self.consumption),
                "execution_plan": self.execution_plan.to_dict() if self.execution_plan else {},
                "project_intelligence": dict(self.project_intelligence)}


class Orchestrator:
    def __init__(self, database: Database, provider: AIProvider, events: EventBus | None = None,
                 provider_name: str | None = None,
                 profiles: WorkProfileRegistry | None = None,
                 providers: ProviderRegistry | None = None,
                 models: ModelRegistry | None = None,
                 provider_preference: Sequence[str] = ("auto",),
                 active_profiles: Sequence[str] = (),
                 consumption_mode: str = "balanced"):
        self.database = database
        self.events = events or EventBus(database)
        self.provider = provider
        self.provider_name = provider_name or getattr(provider, "id", None) or "mock"
        self.active_profiles = list(active_profiles)
        self.consumption_policy: ConsumptionPolicy = consumption_policy(consumption_mode)

        # V2 universal path.
        self.profiles = profiles or profile_registry()
        self.provider_registry = providers or provider_registry()
        self.models = models or ModelRegistry.from_yaml(RESOURCE_ROOT / "config" / "models.yaml",
                                                        platform_home() / "models.yaml")
        self.analyzer = GoalAnalyzer(profiles=self.profiles)
        self.composer = TeamComposer(self.profiles, EvaluationRegistry(), self.consumption_policy)
        self.universal_planner = UniversalPlanner()
        self.capability_router = CapabilityRouter(self.models, self.provider_registry, database,
                                                  preferences=provider_preference,
                                                  policy=self.consumption_policy)
        self.tools = ToolRegistry.default()
        self.skills = SkillRegistry.from_yaml(RESOURCE_ROOT / "config" / "default_skills.yaml")

    # -- composition -------------------------------------------------------

    def compose(self, run_id: str, goal: str, working_directory: str | None = None,
                project_name: str = "project", project_type: str = "unknown",
                project_signals: Sequence[str] = (), constraints: Sequence[str] = (),
        approvals: Sequence[str] = (), record_intelligence: bool = False,
        intelligence_directory: str | None = None) -> Composition:
        analysis = self.analyzer.analyze(goal, self.active_profiles, project_signals)
        intelligence = ContextSelection("cold", "project adapter unavailable")
        intelligence_root = intelligence_directory or working_directory
        if intelligence_root and (Path(intelligence_root) / ".agent").is_dir():
            intelligence = ProjectIntelligenceStore(Path(intelligence_root)).select(
                goal, analysis.capabilities, record_reuse=record_intelligence)
        self.skills.discover_directory(RESOURCE_ROOT / "skills", SkillTrust.BUILT_IN)
        self.skills.discover_directory(platform_home() / "skills", SkillTrust.TRUSTED)
        if working_directory:
            self.skills.discover_directory(Path(working_directory) / ".agent" / "skills",
                                           SkillTrust.PROJECT_LOCAL)
        execution = ExecutionPlanner(
            self.tools, SkillResolver(self.skills.manifests()),
            minimize_cost=self.consumption_policy.mode.value == "economy").plan(goal, analysis)
        for manifest in execution.temporary_skills:
            self.skills.register_manifest(manifest, replace=True)
        resolver = CapabilityResolver(
            AgentRegistry.from_yaml(RESOURCE_ROOT / "config" / "default_agents.yaml"),
            self.skills,
            self.tools, TeamManager(AgentRegistry(), self.events))
        if execution.strategy in {ExecutionStrategy.MULTI_AGENT_DAG,
                                   ExecutionStrategy.MULTI_AGENT_PARALLEL}:
            team = self.composer.compose(analysis, resolver, run_id, constraints)
            self._assign_selected_skills(team, execution)
        else:
            team = self._minimum_team(analysis, execution, constraints)
        self._reuse_project_roles(team, intelligence)
        execution.ai_agents = len(team.members)
        execution.expected_handoffs = max(0, len(team.members) - 1)
        graph = self.universal_planner.plan(run_id, goal, analysis, team, execution)
        rationale = self._route(graph, analysis, team, working_directory, project_name,
                                project_type, approvals)
        for task in graph.tasks.values():
            task.metadata["project_intelligence"] = intelligence.to_dict()
        return Composition(analysis, team, graph, rationale,
                           consumption=self.consumption_policy.to_dict(), execution_plan=execution,
                           project_intelligence=intelligence.to_dict())

    @staticmethod
    def _reuse_project_roles(team: TeamPlan, intelligence: ContextSelection) -> None:
        """Reuse a validated thin project role when it covers an already-needed responsibility."""
        reusable = [item for item in intelligence.items if item.get("kind") == "agent"
                    and item.get("validation") in {"validated", "measured"}]
        for item in reusable:
            wanted = set(item.get("capabilities", []))
            candidates = [(len(wanted & set(member.capabilities)), member) for member in team.members]
            overlap, member = max(candidates, default=(0, None), key=lambda value: value[0])
            if not member or overlap == 0:
                continue
            previous = member.role_id
            member.role_id = str(item["id"])
            member.name = str(item["id"]).replace("-", " ").replace("_", " ").title()
            member.responsibility = str(item["summary"])
            member.origin = "project_intelligence"
            member.reason = f"Reused validated project role for {overlap} required capabilities; replaced {previous}."
            team.rationale.append(f"Reused project role {member.role_id}; no equivalent role was regenerated.")

    def _minimum_team(self, analysis: GoalAnalysis, execution: ExecutionPlan,
                      constraints: Sequence[str]) -> TeamPlan:
        profile_gates = {gate for profile_id in analysis.profiles
                         for gate in ((self.profiles.get(profile_id).approval_gates)
                                      if self.profiles.get(profile_id) else [])}
        gates = sorted(set(analysis.approval_gates) & profile_gates
                       | {gate for gate in analysis.approval_gates if gate in constraints})
        if execution.strategy in {ExecutionStrategy.TOOL_ONLY, ExecutionStrategy.ARTIFACT_ONLY,
                                   ExecutionStrategy.HUMAN_APPROVAL}:
            return TeamPlan([], analysis.complexity, analysis.risk, list(analysis.profiles),
                            list(analysis.capabilities), list(execution.reasons), tools=execution.tools,
                            approval_gates=gates, consumption_mode=self.consumption_policy.mode.value)
        wanted = set(analysis.capabilities)
        roles = [role for role in self.profiles.roles(analysis.profiles) if not role.evaluative]
        role = max(roles, key=lambda item: (len(wanted & set(item.capabilities)), -item.stage),
                   default=None)
        omitted = [{"role": item.name,
                    "reason": "one reasoning responsibility is sufficient for this execution plan"}
                   for item in roles if role is not None and item.id != role.id]
        selected_skills = [item.manifest.id for item in execution.selected_skills]
        member = TeamMember(
            role.id if role else "general_executor", role.name if role else "General Executor",
            role.responsibility if role else "Carry the goal end to end.", sorted(wanted),
            selected_skills, role.profile if role else (analysis.profiles or ["general"])[0],
            role.stage if role else 50, read_only=analysis.read_only,
            reason="One reasoning responsibility covers all required capabilities.")
        declared: list[str] = []
        profile = self.profiles.get(role.profile) if role else None
        if profile:
            declared.extend(profile.evaluation)
        for candidate in execution.selected_skills:
            declared.extend(candidate.manifest.evaluation)
        candidates = EvaluationRegistry().resolve(declared)
        evaluations = [item for item in candidates if item.kind is EvaluationKind.DETERMINISTIC
                       and item.tool in execution.tools]
        if not evaluations and analysis.complexity.value != "trivial":
            fallback = EvaluationRegistry().get("goal_coverage")
            if fallback:
                evaluations = [fallback]
        rationale = list(execution.reasons)
        skipped_profiles = [item for item in analysis.profiles
                            if role is not None and item != role.profile]
        if skipped_profiles:
            rationale.append(f"Evaluation uses {role.profile}; {', '.join(skipped_profiles)} did not draw on "
                             "the capabilities required by this goal.")
        return TeamPlan([member], analysis.complexity, analysis.risk, list(analysis.profiles),
                        sorted(wanted), rationale, omitted=omitted,
                        evaluation=evaluations,
                        tools=execution.tools, approval_gates=gates,
                        consumption_mode=self.consumption_policy.mode.value)

    @staticmethod
    def _assign_selected_skills(team: TeamPlan, execution: ExecutionPlan) -> None:
        for member in team.members:
            member.skills = [candidate.manifest.id for candidate in execution.selected_skills
                             if set(candidate.matched) & set(member.capabilities)]

    def _route(self, graph: TaskGraph, analysis: GoalAnalysis, team: TeamPlan,
               working_directory: str | None, project_name: str, project_type: str,
               approvals: Sequence[str]) -> list[dict[str, Any]]:
        available = self._available_providers()
        rationale: list[dict[str, Any]] = []
        for task in graph.tasks.values():
            task.metadata.update({"project_name": project_name, "project_type": project_type,
                                  "approvals": list(approvals)})
            if working_directory:
                task.metadata["working_directory"] = working_directory
            if task.kind is not TaskKind.AGENT:
                task.metadata["routing"] = {"provider": "none", "model": None,
                                            "reason": f"{task.kind.value} task; no AI invocation required.",
                                            "reasons": [f"{task.kind.value} task; no AI invocation required."],
                                            "agent": task.owner, "task_type": task.metadata.get("task_type", "unknown"),
                                            "model_class": "none", "reasoning": "none"}
                task.metadata["routing_reason"] = task.metadata["routing"]["reason"]
                task.metadata["model"] = None
                continue
            requirements = Requirement.many(task.required_capabilities or analysis.capabilities)
            local_mutation = {"coding", "implementation", "debugging", "refactoring",
                              "build", "configuration", "testing", "code_review"}
            if (not task.metadata.get("read_only") and
                    local_mutation.intersection(task.required_capabilities)):
                requirements = Requirement.many([
                    *requirements,
                    Requirement("filesystem", reason="task modifies a local project"),
                    Requirement("write_access", reason="task writes project artifacts"),
                    Requirement("repository_access", reason="task requires repository context"),
                ])
            decision = self.capability_router.route(
                requirements, analysis.risk, analysis.complexity,
                task.metadata.get("task_type", "unknown"), task.owner, available)
            task.model_class = decision.model_class
            task.reasoning = decision.reasoning
            task.metadata.update({"model": decision.model, "provider": decision.provider,
                                  "routing": decision.to_dict(), "routing_reason": decision.reason,
                                  "capability_signature": decision.capability_signature})
            task.metadata["provider_profile"] = self._provider_profile(decision.provider, task.owner)
            rationale.append({"task_id": task.id, "role": task.owner, **decision.to_dict()})
        return rationale

    def _available_providers(self) -> list[str]:
        ready = self.provider_registry.ready_ids()
        # The explicitly injected provider is always available to the current
        # run. Mock is otherwise excluded whenever a real backend is ready.
        if self.provider_name not in ready:
            ready.insert(0, self.provider_name)
        real = [item for item in ready if item != "mock"]
        if self.provider_name == "mock":
            return ["mock"]
        return [self.provider_name] + [item for item in real if item != self.provider_name]

    def _provider_profile(self, provider: str, role: str) -> str | None:
        if provider not in self.provider_registry:
            return None
        return self.provider_registry.profile_for(provider, role)

    # -- planning ----------------------------------------------------------

    def plan_goal(self, run_id: str, goal: str, working_directory: str | None = None,
                  project_name: str = "project", project_type: str = "unknown"):
        """Analyze a goal and return its capability-driven task graph."""
        return self.plan(run_id, goal, working_directory, project_name, project_type).graph

    def plan(self, run_id: str, goal: str, working_directory: str | None = None,
             project_name: str = "project", project_type: str = "unknown",
             project_signals: Sequence[str] = (), constraints: Sequence[str] = (),
             approvals: Sequence[str] = ()) -> Composition:
        return self.compose(run_id, goal, working_directory, project_name, project_type,
                            project_signals, constraints, approvals)

    # -- execution ---------------------------------------------------------

    async def run_goal(self, goal: str, project_id: str | None = None,
                       working_directory: str | None = None, run_id: str | None = None,
                       project_name: str = "project", project_type: str = "unknown",
                       orchestration_owner: str = "universal-agent-platform", entry_source: str = "cli",
                       project_signals: Sequence[str] = (), constraints: Sequence[str] = (),
                       approvals: Sequence[str] = ()) -> str:
        run_id = run_id or new_id("RUN")
        self.database.execute(
            "INSERT INTO runs(id,project_id,goal,status,orchestration_owner,entry_source) VALUES(?,?,?,'running',?,?)",
            (run_id, project_id, goal, orchestration_owner, entry_source))
        self.events.emit(Event("run_created", run_id, metadata={"goal": goal,
                         "orchestration_owner": orchestration_owner, "entry_source": entry_source}))
        intelligence_directory = None
        if project_id:
            rows = self.database.query("SELECT path FROM projects WHERE id=?", (project_id,))
            intelligence_directory = rows[0]["path"] if rows else None
        composition = self.compose(run_id, goal, working_directory, project_name, project_type,
                                   project_signals, constraints, approvals, record_intelligence=True,
                                   intelligence_directory=intelligence_directory)
        intelligence_store = None
        intelligence_root = intelligence_directory or working_directory
        if intelligence_root and (Path(intelligence_root) / ".agent").is_dir():
            intelligence_store = ProjectIntelligenceStore(Path(intelligence_root))
            intelligence_store.record_run(run_id, ContextSelection(**composition.project_intelligence))
            self.database.execute(
                "INSERT INTO project_intelligence_runs(run_id,temperature,reason,reuse_hits,rediscovery_count,"
                "context_chars,estimated_tokens,data_json) VALUES(?,?,?,?,?,?,?,?)",
                (run_id, composition.project_intelligence["temperature"],
                 composition.project_intelligence["reason"], composition.project_intelligence["reuse_hits"],
                 composition.project_intelligence["rediscovery_count"],
                 composition.project_intelligence["context_chars"],
                 composition.project_intelligence["estimated_tokens"],
                 self.database.json(composition.project_intelligence)))
        graph = composition.graph
        if composition.execution_plan:
            for manifest in composition.execution_plan.temporary_skills:
                self.database.execute(
                    "INSERT OR IGNORE INTO skill_versions(skill_id,version,trust,status,manifest_json) "
                    "VALUES(?,?,?,?,?)",
                    (manifest.id, manifest.version, manifest.trust.value, manifest.status.value,
                     self.database.json(manifest.to_dict(include_path=False))))
                self.events.emit(Event("skill_synthesized", run_id, metadata={
                    "reason": manifest.provenance.get("creation_reason"),
                    "missing_capability": manifest.capabilities[0] if manifest.capabilities else None,
                    "skill_id": manifest.id, "version": manifest.version,
                    "validation_status": "metadata_validated"}))
        self.database.execute("UPDATE runs SET work_profiles=?,composition_json=? WHERE id=?",
                              (",".join(composition.analysis.profiles),
                               self.database.json(composition.to_dict()), run_id))
        self.events.emit(Event("team_composed", run_id, metadata={
            "members": [item.role_id for item in composition.team.members],
            "complexity": composition.analysis.complexity.value,
            "profiles": composition.analysis.profiles,
            "rationale": composition.team.rationale}))
        for task in graph.tasks.values():
            self.database.execute(
                "INSERT INTO tasks(id,run_id,title,owner,status,priority,data_json,kind) VALUES(?,?,?,?,?,?,?,?)",
                (task.id, task.run_id, task.title, task.owner, task.status.value, task.priority,
                 self.database.json(task.to_dict()), task.kind.value),
            )
            self.events.emit(Event("task_created", run_id, task.owner, task.id,
                                   {"dependencies": task.dependencies, "kind": task.kind.value,
                                    "routing": task.metadata["routing"]}))
        try:
            success = await Scheduler(self.database, self.events, self.provider,
                                      provider_name=self.provider_name,
                                      capability_router=self.capability_router,
                                      tools=self.tools, approvals=approvals,
                                      provider_registry=self.provider_registry,
                                      skill_registry=self.skills,
                                      max_parallel_agents=self.consumption_policy.max_parallel_agents,
                                      max_parallel_strong_agents=self.consumption_policy.max_parallel_strong_agents,
                                      max_escalations=self.consumption_policy.max_escalations_per_task,
                                      receipt_word_limit=self.consumption_policy.receipt_word_limit,
                                      max_context_receipts=self.consumption_policy.max_context_receipts).run(graph)
        except asyncio.CancelledError:
            self.database.execute("UPDATE runs SET status='cancelled',completed_at=? WHERE id=?", (now_iso(), run_id))
            raise
        status = "completed" if success else "failed"
        self.database.execute("UPDATE runs SET status=?,completed_at=? WHERE id=?", (status, now_iso(), run_id))
        self.events.emit(Event(f"run_{status}", run_id))
        if intelligence_store:
            from adaptive_agent.project.discovery import discover

            if composition.project_intelligence["temperature"] == "cold":
                intelligence_store.learn_discovery(discover(Path(intelligence_root)), run_id)
            reported_files: list[str] = []
            for row in self.database.query(
                    "SELECT data_json FROM receipts WHERE task_id IN "
                    "(SELECT id FROM tasks WHERE run_id=?)", (run_id,)):
                reported_files.extend(json.loads(row["data_json"]).get("files", []))
            evaluations = self.database.query(
                "SELECT passed FROM artifact_evaluations WHERE run_id=?", (run_id,))
            evaluated = (all(bool(item["passed"]) for item in evaluations) if evaluations else None)
            intelligence_store.distill_run(run_id, status, goal, len(graph.tasks),
                                           reported_files, evaluated)
        return run_id
