"""Minimum-sufficient execution strategy selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from adaptive_agent.core.capabilities import Complexity, Risk, normalize
from adaptive_agent.core.goal_analyzer import GoalAnalysis
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.skills.resolver import SkillCandidate, SkillResolver
from adaptive_agent.skills.manifest import SkillManifest
from adaptive_agent.skills.synthesis import SkillSpecification, TemporarySkillSynthesizer


class ExecutionStrategy(StrEnum):
    TOOL_ONLY = "tool_only"
    SINGLE_AGENT = "single_agent"
    SINGLE_AGENT_WITH_TOOLS = "single_agent_with_tools"
    MULTI_AGENT_PARALLEL = "multi_agent_parallel"
    MULTI_AGENT_DAG = "multi_agent_dag"
    HUMAN_APPROVAL = "human_approval"
    ARTIFACT_ONLY = "artifact_only"


@dataclass(slots=True)
class ExecutionPlan:
    strategy: ExecutionStrategy
    capabilities: list[str]
    selected_skills: list[SkillCandidate] = field(default_factory=list)
    rejected_skills: list[SkillCandidate] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    ai_agents: int = 0
    expected_handoffs: int = 0
    reasons: list[str] = field(default_factory=list)
    temporary_skills: list[SkillManifest] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"strategy": self.strategy.value, "capabilities": self.capabilities,
                "selected_skills": [item.to_dict() for item in self.selected_skills],
                "rejected_skills": [item.to_dict() for item in self.rejected_skills],
                "tools": self.tools, "ai_agents": self.ai_agents,
                "expected_handoffs": self.expected_handoffs, "reasons": self.reasons,
                "temporary_skills": [item.to_dict() for item in self.temporary_skills]}


class ExecutionPlanner:
    def __init__(self, tools: ToolRegistry, skills: SkillResolver, minimize_cost: bool = False,
                 allow_skill_synthesis: bool = False, allow_multi_agent: bool = False,
                 minimal_skills: bool = True):
        self.tools, self.skills, self.minimize_cost = tools, skills, minimize_cost
        self.allow_skill_synthesis = allow_skill_synthesis
        self.allow_multi_agent = allow_multi_agent
        self.minimal_skills = minimal_skills

    def plan(self, goal: str, analysis: GoalAnalysis) -> ExecutionPlan:
        capabilities = sorted({normalize(item) for item in analysis.capabilities})
        deterministic = self.tools.search(capabilities)
        explicit_tool = self._explicit_tool(goal, deterministic)
        selected, rejected = self.skills.select(
            capabilities, self.minimize_cost, minimal=self.minimal_skills)
        covered = {capability for item in selected for capability in item.matched}
        deterministic_capabilities = {capability for tool in deterministic for capability in tool.capabilities}
        skill_tools = {tool for item in selected for tool in item.manifest.tools}
        validation_tools = self._validation_tools(capabilities)
        tool_ids = sorted({item.id for item in deterministic} | skill_tools | validation_tools)

        if explicit_tool and self._operation_only(goal):
            return ExecutionPlan(ExecutionStrategy.TOOL_ONLY, capabilities, [], rejected,
                                 [explicit_tool], 0, 0,
                                 [f"A deterministic allowlisted tool fully satisfies the request: {explicit_tool}."])
        if self._artifact_only(goal):
            return ExecutionPlan(ExecutionStrategy.ARTIFACT_ONLY, capabilities, [], rejected,
                                 [], 0, 0, ["The request only records an existing artifact; no reasoning invocation is justified."])
        if ((analysis.risk is Risk.HIGH and analysis.approval_gates and analysis.read_only)
                or (analysis.approval_gates and self._approval_only(goal))):
            return ExecutionPlan(ExecutionStrategy.HUMAN_APPROVAL, capabilities, [], rejected,
                                 [], 0, 0, ["The only executable step is a mandatory human approval."])

        temporary = (self._temporary_skills(set(capabilities) - covered - deterministic_capabilities)
                     if self.allow_skill_synthesis else [])
        selected.extend(SkillCandidate(item, 0, list(item.capabilities), [],
                                       ["no equivalent tool or reusable Skill was found",
                                        "temporary procedure proposed; promotion requires approval"])
                        for item in temporary)

        reasoning_capabilities = [item for item in capabilities if item not in deterministic_capabilities]
        distinct = self._distinct_responsibilities(reasoning_capabilities)
        if analysis.risk is Risk.HIGH and self.allow_multi_agent:
            return ExecutionPlan(ExecutionStrategy.MULTI_AGENT_DAG, capabilities, selected, rejected,
                                 tool_ids, 2, 1,
                                 ["High-risk work requires an independent reasoning responsibility.",
                                  "Mandatory approval and provider capability checks remain in force."], temporary)
        if (not self.allow_multi_agent or analysis.complexity.rank <= Complexity.SMALL.rank
                or distinct <= 1):
            strategy = (ExecutionStrategy.SINGLE_AGENT_WITH_TOOLS if tool_ids
                        else ExecutionStrategy.SINGLE_AGENT)
            return ExecutionPlan(strategy, capabilities, selected, rejected, tool_ids, 1, 0,
                                 ["Single-agent-first is the default; no team handoff is justified.",
                                  "Reusable Skills were selected from metadata before loading instructions."], temporary)
        agents = min(analysis.complexity.max_team_size, distinct)
        strategy = (ExecutionStrategy.MULTI_AGENT_PARALLEL if analysis.read_only
                    else ExecutionStrategy.MULTI_AGENT_DAG)
        return ExecutionPlan(strategy, capabilities, selected, rejected, tool_ids, agents,
                             max(0, agents - 1),
                             [f"{distinct} distinct reasoning responsibilities require separation.",
                              "Multi-agent execution is capped at the minimum capability coverage."], temporary)

    @staticmethod
    def _operation_only(goal: str) -> bool:
        text = goal.lower().strip()
        verbs = ("run ", "execute ", "check ", "format ", "lint ", "typecheck ", "build ")
        return text.startswith(verbs) and not any(word in text for word in ("fix", "analyze", "design", "implement"))

    @staticmethod
    def _artifact_only(goal: str) -> bool:
        text = goal.lower().strip()
        return any(text.startswith(prefix) for prefix in (
            "record artifact", "register artifact", "catalog artifact", "attach artifact",
            "record the artifact", "register the artifact", "catalog the artifact",
        )) and not any(word in text for word in ("create", "write", "analyze", "review", "modify"))

    @staticmethod
    def _approval_only(goal: str) -> bool:
        text = goal.lower().strip()
        return text.startswith(("approve ", "authorize ", "confirm approval", "request approval"))

    @staticmethod
    def _explicit_tool(goal: str, tools: list) -> str | None:
        text = goal.lower()
        if any(word in text for word in ("pytest", "test suite", "run tests")):
            return "project_test"
        if "build" in text:
            return "project_build"
        return tools[0].id if len(tools) == 1 else None

    @staticmethod
    def _distinct_responsibilities(capabilities: list[str]) -> int:
        groups = {
            "build": {"coding", "implementation", "frontend_implementation", "configuration", "bug_fix"},
            "design": {"design", "responsive_ui", "visual_hierarchy", "interaction_design"},
            "analysis": {"analysis", "research", "requirements", "planning", "architecture"},
            "evaluation": {"review", "accessibility", "testing", "evaluation", "security_review"},
        }
        hits = sum(bool(set(capabilities) & values) for values in groups.values())
        unknown = bool(set(capabilities) - set().union(*groups.values()))
        return max(1, hits + int(unknown))

    @staticmethod
    def _validation_tools(capabilities: list[str]) -> set[str]:
        wanted = set(capabilities)
        mutation = {"coding", "implementation", "frontend_implementation", "bug_fix",
                    "debugging", "refactoring", "python"}
        tools = {"project_test"} if wanted & mutation else set()
        if wanted & {"build", "configuration", "ci_cd"}:
            tools.add("project_build")
        return tools

    @staticmethod
    def _temporary_skills(missing: set[str]) -> list[SkillManifest]:
        agent_native = {"analysis", "planning", "research", "synthesis", "writing", "editing",
                        "review", "evaluation", "goal_analysis", "code_review", "visual_review",
                        "requirements", "prioritization", "comparison", "usability", "coding",
                        "implementation", "frontend_implementation", "bug_fix", "debugging",
                        "refactor", "configuration", "architecture", "design", "wireframing",
                        "visual_direction", "branding", "decision", "orchestration", "strategy"}
        proposed = []
        synthesizer = TemporarySkillSynthesizer()
        for capability in sorted(missing - agent_native):
            spec = SkillSpecification(
                f"temporary-{capability.replace('_', '-')}", capability,
                f"Temporary bounded procedure for {capability}.",
                inputs={"task_context": "object"}, outputs={"evidence": "report"},
                procedure=[f"Apply {capability} only within the assigned task scope.",
                           "Record evidence and assumptions."],
                evaluation=["goal_coverage"],
                creation_reason=f"No trusted Skill matched required capability {capability}.")
            proposed.append(synthesizer.propose(spec))
        return proposed
