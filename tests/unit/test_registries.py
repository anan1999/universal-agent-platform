from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.capability_matcher import CapabilityMatcher
from adaptive_agent.skills.registry import SkillRegistry


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

