from __future__ import annotations

from adaptive_agent.agents.registry import AgentRegistry
from adaptive_agent.core.models import Event
from adaptive_agent.observability.event_bus import EventBus


class TeamManager:
    def __init__(self, registry: AgentRegistry, events: EventBus | None = None):
        self.registry = registry
        self.events = events

    def ensure_capability(self, capability: str, run_id: str) -> tuple[str, str]:
        matches = self.registry.search([capability])
        if matches:
            return matches[0][0], "existing_agent"
        name = f"{capability.replace('-', '_')}_specialist"
        self.registry.register(name, {"type": "temporary", "scope": "current_run_only", "capabilities": [capability], "successful_uses": 0, "promotion_candidate": False, "cost_class": "medium"})
        if self.events:
            self.events.emit(Event("specialist_created", run_id, name, metadata={"capability": capability}))
        return name, "temporary_specialist"

    def record_success(self, name: str, run_id: str) -> bool:
        data = self.registry.all()[name]
        successes = int(data.get("successful_uses", 0)) + 1
        candidate = data.get("type") == "temporary" and successes >= 3
        self.registry.update(name, successful_uses=successes, promotion_candidate=candidate)
        if candidate and self.events:
            self.events.emit(Event("promotion_candidate", run_id, name, metadata={"successful_uses": successes}))
        return candidate

