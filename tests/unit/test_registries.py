from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.capability_matcher import CapabilityMatcher
from adaptive_agent.skills.registry import SkillRegistry
from adaptive_agent.core.capability_resolver import CapabilityResolver, Strategy
from adaptive_agent.core.team_manager import TeamManager


def test_agent_lifecycle_and_capability_match():
    registry = AgentRegistry({"cheap": {"capabilities": ["search"], "cost_class": "low"}, "strong": {"capabilities": ["search", "design"], "cost_class": "high"}})
    assert CapabilityMatcher(registry).match(["search"]) == "cheap"
    registry.disable("cheap")
    assert CapabilityMatcher(registry).match(["search"]) == "strong"
    registry.enable("cheap")
    registry.deprecate("cheap")
    assert registry.search(["search"])[0][0] == "strong"


def test_skill_registry_is_lazy():
    registry = SkillRegistry({"git": {"lazy": True}, "pytest": {"lazy": True}})
    assert registry.loaded == set()
    assert list(registry.load_for(["git"])) == ["git"]
    assert registry.loaded == {"git"}


def test_capability_resolution_attaches_skill_before_creating_specialist():
    agents = AgentRegistry()
    skills = SkillRegistry({"lighting-guide": {"capabilities": ["lighting_design"], "lazy": True}})
    resolver = CapabilityResolver(agents, skills, team_manager=TeamManager(agents))
    result = resolver.resolve("lighting_design", "RUN")
    assert result.strategy is Strategy.ATTACH_SKILL
    assert result.target == "lighting-guide"
    assert agents.all() == {}


def test_missing_judgement_capability_creates_temporary_not_permanent_specialist():
    agents = AgentRegistry()
    resolver = CapabilityResolver(agents, SkillRegistry(), team_manager=TeamManager(agents))
    result = resolver.resolve("lighting_review", "RUN")
    assert result.strategy is Strategy.TEMPORARY_SPECIALIST
    assert agents.all()[result.target]["type"] == "temporary"
    assert agents.all()[result.target]["promotion_candidate"] is False

