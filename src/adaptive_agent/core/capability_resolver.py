"""Generic capability resolution.

    Required capability
        -> an existing agent already capable?      reuse
        -> an existing skill provides it?          attach the skill
        -> a deterministic tool provides it?       use the tool, no agent
        -> a skill can be created?                 create the skill
        -> otherwise                               temporary specialist

Creating an agent is the last resort, and a temporary specialist is never
promoted without explicit human approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable

from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.capabilities import normalize
from adaptive_agent.core.team_manager import TeamManager
from adaptive_agent.core.tools import ToolRegistry
from adaptive_agent.skills.registry import SkillRegistry


class Strategy(StrEnum):
    EXISTING_AGENT = "existing_agent"
    ATTACH_SKILL = "attach_skill"
    DETERMINISTIC_TOOL = "deterministic_tool"
    CREATE_SKILL = "create_skill"
    TEMPORARY_SPECIALIST = "temporary_specialist"


@dataclass(slots=True)
class Resolution:
    capability: str
    strategy: Strategy
    target: str
    reason: str
    #: True when the platform created something that did not exist before.
    created: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"capability": self.capability, "strategy": self.strategy.value,
                "target": self.target, "reason": self.reason, "created": self.created}


@dataclass(slots=True)
class ResolutionPlan:
    resolutions: list[Resolution] = field(default_factory=list)

    def by_strategy(self, strategy: Strategy) -> list[Resolution]:
        return [item for item in self.resolutions if item.strategy is strategy]

    @property
    def skills(self) -> list[str]:
        return sorted({item.target for item in self.resolutions
                       if item.strategy in {Strategy.ATTACH_SKILL, Strategy.CREATE_SKILL}})

    @property
    def tools(self) -> list[str]:
        return sorted({item.target for item in self.by_strategy(Strategy.DETERMINISTIC_TOOL)})

    @property
    def specialists(self) -> list[str]:
        return sorted({item.target for item in self.by_strategy(Strategy.TEMPORARY_SPECIALIST)})

    def to_dict(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.resolutions]


class CapabilityResolver:
    def __init__(self, agents: AgentRegistry, skills: SkillRegistry,
                 tools: ToolRegistry | None = None, team_manager: TeamManager | None = None,
                 allow_specialist_creation: bool = True):
        self.agents = agents
        self.skills = skills
        self.tools = tools or ToolRegistry()
        self.team_manager = team_manager
        self.allow_specialist_creation = allow_specialist_creation

    def resolve(self, capability: str, run_id: str = "") -> Resolution:
        name = normalize(capability)

        agent = self._agent_for(name)
        if agent:
            return Resolution(name, Strategy.EXISTING_AGENT, agent,
                              f"{agent} already declares {name}.")

        skill = self._skill_for(name)
        if skill:
            return Resolution(name, Strategy.ATTACH_SKILL, skill,
                              f"Skill '{skill}' provides {name}; attaching it avoids creating an agent.")

        tool = self._tool_for(name)
        if tool:
            return Resolution(name, Strategy.DETERMINISTIC_TOOL, tool,
                              f"Tool '{tool}' provides {name} deterministically; no AI invocation needed.")

        if self._skill_creatable(name):
            self.skills.register(name, {"description": f"Auto-created skill for {name}.",
                                        "scope": "run", "capabilities": [name], "lazy": True,
                                        "source": "capability_resolver"})
            return Resolution(name, Strategy.CREATE_SKILL, name,
                              f"Created skill '{name}' rather than a new agent.", created=True)

        if not self.allow_specialist_creation or self.team_manager is None:
            return Resolution(name, Strategy.CREATE_SKILL, name,
                              f"No agent, skill, or tool provides {name}; specialist creation is disabled.")

        specialist, origin = self.team_manager.ensure_capability(name, run_id)
        return Resolution(name, Strategy.TEMPORARY_SPECIALIST, specialist,
                          f"Nothing provided {name}; created a temporary specialist "
                          "(promotion requires explicit approval).",
                          created=origin == "temporary_specialist")

    def resolve_all(self, capabilities: Iterable[str], run_id: str = "") -> ResolutionPlan:
        plan = ResolutionPlan()
        for capability in dict.fromkeys(normalize(item) for item in capabilities):
            if capability:
                plan.resolutions.append(self.resolve(capability, run_id))
        return plan

    # -- lookups -----------------------------------------------------------

    def _agent_for(self, capability: str) -> str | None:
        matches = self.agents.search([capability])
        if not matches:
            return None
        ordering = {"low": 0, "medium": 1, "high": 2, "very_high": 3, "unknown": 1}
        return min(matches, key=lambda item: (ordering.get(item[1].get("cost_class", "medium"), 1),
                                              item[0]))[0]

    def _skill_for(self, capability: str) -> str | None:
        for name, spec in self.skills.all().items():
            provided = {normalize(item) for item in (spec or {}).get("capabilities", [])}
            if capability in provided or normalize(name) == capability:
                return name
        return None

    def _tool_for(self, capability: str) -> str | None:
        matches = self.tools.search([capability])
        return matches[0].id if matches else None

    def _skill_creatable(self, capability: str) -> bool:
        """A skill is creatable when it is knowledge, not a distinct reasoning role.

        Capability names that read as procedures or knowledge domains become
        skills. Names that read as a judgement responsibility need an agent.
        """
        judgement = {"review", "evaluation", "critique", "approval", "decision",
                     "orchestration", "planning", "strategy"}
        return not any(word in capability for word in judgement)
