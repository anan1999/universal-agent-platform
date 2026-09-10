"""Capability-first provider and model routing.

Routing uses `required capabilities + risk + history + availability -> (provider, model)`.
The agent role is supporting information and a weak tiebreak at most; it is
never the routing key, and no model name appears in this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from adaptive_agent.core.capabilities import (
    Complexity,
    Level,
    Requirement,
    Risk,
    signature,
)
from adaptive_agent.models.registry import ModelDescriptor, ModelRegistry
from adaptive_agent.providers.registry import ProviderRegistry
from adaptive_agent.core.capabilities import Support
from adaptive_agent.core.consumption import ConsumptionPolicy, consumption_policy
from adaptive_agent.storage.database import Database


#: Minimum strength a task of each complexity wants from its primary capabilities.
COMPLEXITY_FLOOR = {
    Complexity.TRIVIAL: Level.LOW,
    Complexity.SMALL: Level.LOW,
    Complexity.NORMAL: Level.MEDIUM,
    Complexity.COMPLEX: Level.HIGH,
    Complexity.CRITICAL: Level.VERY_HIGH,
}

RISK_FLOOR = {Risk.LOW: Level.LOW, Risk.MEDIUM: Level.MEDIUM, Risk.HIGH: Level.HIGH}


@dataclass(slots=True)
class Candidate:
    provider: str
    model: str
    model_id: str
    score: float
    reasons: list[str] = field(default_factory=list)
    disqualified: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "model_id": self.model_id,
                "score": round(self.score, 3), "reasons": list(self.reasons),
                "disqualified": self.disqualified}


@dataclass(slots=True)
class RoutingDecision:
    """Why this provider and this model. Renderable verbatim by presentation clients."""

    provider: str
    model: str | None
    reasoning: str
    capability_signature: str
    required_capabilities: list[str]
    risk: str
    complexity: str
    reasons: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    historical_samples: int = 0
    #: Descriptive strength summary used for escalation and concurrency limits.
    model_class: str = "standard"
    #: Agent is supporting metadata and not a routing input.
    agent: str = ""
    task_type: str = "unknown"

    @property
    def reason(self) -> str:
        return " ".join(self.reasons)

    def to_dict(self) -> dict[str, Any]:
        return {"provider": self.provider, "model": self.model, "reasoning": self.reasoning,
                "capability_signature": self.capability_signature,
                "required_capabilities": list(self.required_capabilities),
                "risk": self.risk, "complexity": self.complexity, "reasons": list(self.reasons),
                "reason": self.reason, "candidates": list(self.candidates),
                "historical_samples": self.historical_samples, "model_class": self.model_class,
                "agent": self.agent, "task_type": self.task_type}


class CapabilityRouter:
    def __init__(self, models: ModelRegistry, providers: ProviderRegistry,
                 database: Database | None = None, preferences: Sequence[str] = ("auto",),
                 minimum_history_samples: int = 5,
                 policy: ConsumptionPolicy | None = None):
        self.models = models
        self.providers = providers
        self.database = database
        self.preferences = [str(item) for item in preferences] or ["auto"]
        self.minimum_history_samples = minimum_history_samples
        self._provider_capabilities: dict[str, Any] = {}
        self.policy = policy or consumption_policy()

    # -- provider selection ------------------------------------------------

    def allowed_providers(self, available: Sequence[str] | None = None) -> list[str]:
        """Provider ids the router may use, in preference order."""
        pool = list(available) if available is not None else self.providers.implemented_ids()
        if "auto" in self.preferences:
            explicit = [item for item in self.preferences if item != "auto" and item in pool]
            return explicit + [item for item in pool if item not in explicit]
        ordered = [item for item in self.preferences if item in pool]
        return ordered or pool

    # -- routing -----------------------------------------------------------

    def route(self, requirements: Iterable[Any], risk: Any = Risk.LOW,
              complexity: Any = Complexity.NORMAL, task_type: str = "unknown",
              agent_role: str = "", available_providers: Sequence[str] | None = None,
              constraints: Sequence[str] = ()) -> RoutingDecision:
        wanted = Requirement.many(requirements)
        risk_value = Risk.coerce(risk)
        complexity_value = Complexity.coerce(complexity)
        providers = self.allowed_providers(available_providers)
        floor = max(COMPLEXITY_FLOOR[complexity_value], RISK_FLOOR[risk_value], key=lambda item: item.rank)
        capability_key = signature(item.name for item in wanted)
        history = self._history(capability_key)

        candidates: list[Candidate] = []
        for model in self.models.all():
            if not model.enabled or model.provider not in providers:
                continue
            candidates.append(self._score(model, wanted, floor, providers, history, constraints, agent_role))

        viable = [item for item in candidates if item.disqualified is None]
        viable.sort(key=lambda item: (-item.score, item.provider, item.model))
        samples = sum(int(row["task_count"]) for row in history.values())

        if not viable:
            reasons = ["No model in the catalog satisfies the mandatory capabilities for this task."]
            if candidates:
                reasons.append("Closest candidates were disqualified: " +
                               "; ".join(f"{item.model} ({item.disqualified})" for item in candidates[:3]) + ".")
            fallback = providers[0] if providers else "mock"
            return RoutingDecision(fallback, None, "medium", capability_key,
                                   [item.name for item in wanted], risk_value.value,
                                   complexity_value.value, reasons,
                                   [item.to_dict() for item in candidates[:5]], samples)

        best = viable[0]
        earlier = providers[:providers.index(best.provider)] if best.provider in providers else []
        rejected_earlier = [item for item in candidates
                            if item.provider in earlier and item.disqualified]
        if rejected_earlier:
            rejected = rejected_earlier[0]
            best.reasons.append(
                f"Preferred provider {rejected.provider} rejected: {rejected.disqualified}; "
                f"selected {best.provider} instead."
            )
        descriptor = self.models.get(best.model)
        reasoning = self.policy.reasoning(self._reasoning(floor, risk_value, descriptor), risk_value)
        decision = RoutingDecision(
            provider=best.provider, model=best.model, reasoning=reasoning,
            capability_signature=capability_key,
            required_capabilities=[item.name for item in wanted],
            risk=risk_value.value, complexity=complexity_value.value,
            reasons=best.reasons,
            candidates=[item.to_dict() for item in viable[:5]] +
                       [item.to_dict() for item in candidates if item.disqualified][:5],
            historical_samples=samples, model_class=self._model_class(descriptor),
            agent=agent_role, task_type=task_type)
        return decision

    # -- scoring -----------------------------------------------------------

    def _score(self, model: ModelDescriptor, wanted: list[Requirement], floor: Level,
               providers: Sequence[str], history: dict[str, dict[str, float]],
               constraints: Sequence[str], agent_role: str) -> Candidate:
        reasons: list[str] = []
        score = 0.0
        matched, attempted = [], []
        provider_capabilities = self._provider_capabilities.get(model.provider)
        if provider_capabilities is None:
            provider_capabilities = self.providers.instance(model.provider).capabilities()
            self._provider_capabilities[model.provider] = provider_capabilities
        for requirement in wanted:
            provider_support = provider_capabilities.get(requirement.name)
            if provider_support is Support.UNSUPPORTED and requirement.mandatory:
                return Candidate(model.provider, model.id, model.model_id, 0.0,
                                 [f"{model.provider} declares {requirement.name} unsupported."],
                                 disqualified=f"provider lacks {requirement.name}")
            actual = model.level(requirement.name)
            target = requirement.level if requirement.level is not Level.UNKNOWN else floor
            if actual is Level.NONE:
                if requirement.mandatory:
                    return Candidate(model.provider, model.id, model.model_id, 0.0,
                                     [f"Declares no support for {requirement.name}."],
                                     disqualified=f"cannot do {requirement.name}")
                continue
            if actual is Level.UNKNOWN:
                score += 0.25
                attempted.append(requirement.name)
                continue
            matched.append(requirement.name)
            score += 2.0 if actual.rank >= target.rank else 1.0
        if matched:
            reasons.append("Declares " + ", ".join(sorted(matched)[:6]) + ".")
        if attempted:
            reasons.append("No declared level for " + ", ".join(sorted(attempted)[:4]) +
                           "; treated as attemptable rather than blocking.")

        # Strength fit: reward meeting the floor without paying for far more.
        strengths = [model.level(item.name).rank for item in wanted if model.level(item.name) is not Level.UNKNOWN]
        if strengths:
            average = sum(strengths) / len(strengths)
            score += 1.5 if average >= floor.rank else -1.0 * (floor.rank - average)
            if average > floor.rank + 1:
                score -= 0.75
                reasons.append("Stronger than this task requires; kept as a candidate but not preferred.")

        # Cost and latency: cheaper and faster wins when capability is equal.
        score -= self.policy.cost_weight * model.cost_rank
        score -= 0.15 * model.latency_rank

        # Availability.
        if model.availability == "always":
            score += 0.25
        elif model.availability == "unavailable":
            return Candidate(model.provider, model.id, model.model_id, 0.0,
                             ["Marked unavailable in the catalog."], disqualified="unavailable")

        # Provider preference order.
        try:
            score += max(0.0, 1.0 - 0.3 * providers.index(model.provider))
            if providers.index(model.provider) == 0 and len(providers) > 1:
                reasons.append(f"{model.provider} is the preferred provider for this project.")
        except ValueError:  # pragma: no cover - filtered earlier
            pass

        # Historical success for this capability signature on this exact model.
        stats = history.get(model.model_id) or history.get(model.id)
        if stats and stats["task_count"] >= self.minimum_history_samples:
            score += 2.0 * (stats["success_rate"] - 0.5)
            score -= 1.0 * stats["escalation_rate"]
            reasons.append(f"Historical success {stats['success_rate']:.0%} over "
                           f"{int(stats['task_count'])} comparable tasks.")

        # Explicit constraints from the project manifest.
        if "prefer_local" in constraints and model.provider == "ollama":
            score += 1.0
        if "prefer_low_cost" in constraints:
            score -= 0.5 * model.cost_rank

        # Agent role is a weak tiebreak only, and only when the catalog tags it.
        if agent_role and agent_role in model.tags:
            score += 0.2

        if not reasons:
            reasons.append("Capability profile is compatible with the task requirements.")
        return Candidate(model.provider, model.id, model.model_id, score, reasons)

    def _reasoning(self, floor: Level, risk: Risk, model: ModelDescriptor | None) -> str:
        if risk is Risk.HIGH or floor.rank >= Level.VERY_HIGH.rank:
            return "high"
        if floor.rank <= Level.LOW.rank:
            return "low"
        return "medium"

    def _model_class(self, model: ModelDescriptor | None) -> str:
        """Descriptive strength summary for escalation, concurrency, and the UI."""
        if model is None:
            return "standard"
        return {"fast": "cheap", "balanced": "standard", "strong": "strong",
                "frontier": "strongest"}.get(model.tier, {0: "cheap", 1: "cheap", 2: "standard",
                                                          3: "strong", 4: "strongest"}[model.cost_rank])

    def _history(self, capability_signature: str) -> dict[str, dict[str, float]]:
        if not self.database:
            return {}
        rows = self.database.query(
            "SELECT model,COUNT(*) task_count,AVG(success) success_rate,AVG(escalated) escalation_rate "
            "FROM agent_performance WHERE capability_signature=? AND model IS NOT NULL GROUP BY model",
            (capability_signature,))
        return {str(row["model"]): row for row in rows if row["task_count"]}

    # -- escalation --------------------------------------------------------

    def escalate(self, decision: RoutingDecision, exclude: Sequence[str] = ()) -> RoutingDecision | None:
        """Next-strongest viable candidate, or None when no safer route remains."""
        blocked = {decision.model, *exclude}
        for candidate in decision.candidates:
            if candidate["model"] in blocked or candidate["disqualified"]:
                continue
            stronger = self.models.get(candidate["model"])
            current = self.models.get(decision.model or "")
            if stronger is None:
                continue
            if current is not None and stronger.cost_rank <= current.cost_rank:
                continue
            return RoutingDecision(
                candidate["provider"], candidate["model"], "high", decision.capability_signature,
                decision.required_capabilities, decision.risk, decision.complexity,
                [f"Escalated from {decision.model}.", *candidate["reasons"]], decision.candidates,
                decision.historical_samples, self._model_class(stronger), decision.agent, decision.task_type)
        return None
