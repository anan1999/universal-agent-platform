from adaptive_agent.agents.registry import AgentRegistry


class CapabilityMatcher:
    def __init__(self, registry: AgentRegistry):
        self.registry = registry

    def match(self, required: list[str]) -> str | None:
        matches = self.registry.search(required)
        if not matches:
            return None
        return min(matches, key=lambda item: ({"low": 0, "medium": 1, "high": 2}.get(item[1].get("cost_class", "medium"), 1), item[0]))[0]

