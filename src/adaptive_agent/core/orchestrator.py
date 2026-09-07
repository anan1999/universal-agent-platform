from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Sequence

from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.capabilities import Requirement
from adaptive_agent.core.capability_resolver import CapabilityResolver
from adaptive_agent.core.capability_router import CapabilityRouter
from adaptive_agent.core.evaluation import EvaluationRegistry
from adaptive_agent.core.goal_analyzer import GoalAnalysis, GoalAnalyzer
from adaptive_agent.core.models import Event, TaskKind, new_id, now_iso
from adaptive_agent.core.scheduler import Scheduler
from adaptive_agent.core.team_composer import TeamComposer, TeamPlan
from adaptive_agent.core.team_manager import TeamManager
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.core.universal_planner import UniversalPlanner
from adaptive_agent.models.registry import ModelRegistry
from adaptive_agent.observability.event_bus import EventBus
from adaptive_agent.profiles.registry import WorkProfileRegistry, profile_registry
from adaptive_agent.providers.base import AIProvider
from adaptive_agent.providers.registry import ProviderRegistry, providers as provider_registry
from adaptive_agent.runtime import PACKAGE_ROOT, platform_home
from adaptive_agent.skills.registry import SkillRegistry
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

    def to_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "analysis": self.analysis.to_dict(),
                "team": self.team.to_dict(), "provider_rationale": list(self.provider_rationale)}


class Orchestrator:
    def __init__(self, database: Database, provider: AIProvider, events: EventBus | None = None,
                 provider_name: str | None = None,
                 profiles: WorkProfileRegistry | None = None,
                 providers: ProviderRegistry | None = None,
                 models: ModelRegistry | None = None,
                 provider_preference: Sequence[str] = ("auto",),
                 active_profiles: Sequence[str] = ()):
        self.database = database
        self.events = events or EventBus(database)
        self.provider = provider
        self.provider_name = provider_name or getattr(provider, "id", None) or "mock"
        self.active_profiles = list(active_profiles)

        # V2 universal path.
        self.profiles = profiles or profile_registry()
        self.provider_registry = providers or provider_registry()
        self.models = models or ModelRegistry.from_yaml(PACKAGE_ROOT / "config" / "models.yaml",
                                                        platform_home() / "models.yaml")
        self.analyzer = GoalAnalyzer(profiles=self.profiles)
        self.composer = TeamComposer(self.profiles, EvaluationRegistry())
        self.universal_planner = UniversalPlanner()
        self.capability_router = CapabilityRouter(self.models, self.provider_registry, database,
                                                  preferences=provider_preference)
        self.tools = ToolRegistry.default()

    # -- composition -------------------------------------------------------

    def compose(self, run_id: str, goal: str, working_directory: str | None = None,
                project_name: str = "project", project_type: str = "unknown",
                project_signals: Sequence[str] = (), constraints: Sequence[str] = (),
                approvals: Sequence[str] = ()) -> Composition:
        analysis = self.analyzer.analyze(goal, self.active_profiles, project_signals)
        resolver = CapabilityResolver(
            AgentRegistry.from_yaml(PACKAGE_ROOT / "config" / "default_agents.yaml"),
            SkillRegistry.from_yaml(PACKAGE_ROOT / "config" / "default_skills.yaml"),
            self.tools, TeamManager(AgentRegistry(), self.events))
        team = self.composer.compose(analysis, resolver, run_id, constraints)
        graph = self.universal_planner.plan(run_id, goal, analysis, team)
        rationale = self._route(graph, analysis, team, working_directory, project_name,
                                project_type, approvals)
        return Composition(analysis, team, graph, rationale)

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
        implemented = self.provider_registry.implemented_ids()
        # The scheduler executes with the injected provider unless a task names
        # another one, so that provider is always considered available.
        if self.provider_name and self.provider_name not in implemented:
            implemented.append(self.provider_name)
        return [self.provider_name] + [item for item in implemented if item != self.provider_name]

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
        composition = self.plan(run_id, goal, working_directory, project_name, project_type,
                                project_signals, constraints, approvals)
        graph = composition.graph
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
                                      provider_registry=self.provider_registry).run(graph)
        except asyncio.CancelledError:
            self.database.execute("UPDATE runs SET status='cancelled',completed_at=? WHERE id=?", (now_iso(), run_id))
            raise
        status = "completed" if success else "failed"
        self.database.execute("UPDATE runs SET status=?,completed_at=? WHERE id=?", (status, now_iso(), run_id))
        self.events.emit(Event(f"run_{status}", run_id))
        return run_id
