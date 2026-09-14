"""Quota-conscious orchestration policies.

These policies shape orchestration overhead without weakening mandatory
provider capabilities, deterministic checks, or human approval gates.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from adaptive_agent.core.capabilities import Risk


class ConsumptionMode(StrEnum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    MAXIMUM = "maximum"

    @classmethod
    def coerce(cls, value: Any) -> "ConsumptionMode":
        try:
            return cls(str(value or cls.BALANCED.value).lower())
        except ValueError as error:
            choices = ", ".join(item.value for item in cls)
            raise ValueError(f"unknown consumption mode: {value!r}; choose {choices}") from error


@dataclass(frozen=True, slots=True)
class ConsumptionPolicy:
    mode: ConsumptionMode
    max_parallel_agents: int
    max_parallel_strong_agents: int
    max_escalations_per_task: int
    max_team_members: int | None
    receipt_word_limit: int
    max_context_receipts: int
    cost_weight: float
    reasoning_bias: int

    def team_limit(self, normal_limit: int, risk: Risk) -> int:
        if self.max_team_members is None:
            return normal_limit
        # High-risk work may retain an independent reviewer. Execution remains
        # sequential in economy mode, so this does not create agent fan-out.
        safety_limit = 2 if risk is Risk.HIGH else self.max_team_members
        return min(normal_limit, safety_limit)

    def reasoning(self, baseline: str, risk: Risk) -> str:
        if risk is Risk.HIGH:
            return "high"
        levels = ["low", "medium", "high"]
        current = levels.index(baseline) if baseline in levels else 1
        return levels[max(0, min(len(levels) - 1, current + self.reasoning_bias))]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        return data


@dataclass(frozen=True, slots=True)
class ExecutionBudget:
    """Explicit per-run limits.

    Provider/tool calls and wall time are hard orchestration limits. Token limits
    are checked before and after provider calls; a single backend invocation can
    exceed the remaining token allowance when that backend cannot stop mid-call.
    """

    max_provider_calls: int | None = None
    max_provider_tool_calls: int | None = None
    max_provider_messages: int | None = None
    max_tool_calls: int | None = None
    max_total_tokens: int | None = None
    max_output_tokens: int | None = None
    max_retry_rounds: int | None = None
    max_wall_seconds: float | None = None
    verification_reserve_percent: int = 20
    on_exhausted: str = "stop_and_report"

    def __post_init__(self) -> None:
        integer_fields = (
            "max_provider_calls", "max_provider_tool_calls", "max_provider_messages",
            "max_tool_calls", "max_total_tokens",
            "max_output_tokens", "max_retry_rounds",
        )
        for name in integer_fields:
            value = getattr(self, name)
            if value is not None and value < 0:
                raise ValueError(f"{name} must be zero or greater")
        if self.max_wall_seconds is not None and self.max_wall_seconds <= 0:
            raise ValueError("max_wall_seconds must be greater than zero")
        if not 0 <= self.verification_reserve_percent <= 90:
            raise ValueError("verification_reserve_percent must be between 0 and 90")
        if self.on_exhausted != "stop_and_report":
            raise ValueError("on_exhausted must be 'stop_and_report'")

    @property
    def enabled(self) -> bool:
        return any(value is not None for value in (
            self.max_provider_calls, self.max_provider_tool_calls, self.max_provider_messages,
            self.max_tool_calls, self.max_total_tokens,
            self.max_output_tokens, self.max_retry_rounds, self.max_wall_seconds,
        ))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"enabled": self.enabled}


POLICIES = {
    ConsumptionMode.ECONOMY: ConsumptionPolicy(
        ConsumptionMode.ECONOMY, 1, 1, 1, 1, 80, 2, 0.8, -1),
    ConsumptionMode.BALANCED: ConsumptionPolicy(
        ConsumptionMode.BALANCED, 3, 1, 2, None, 160, 4, 0.35, 0),
    ConsumptionMode.MAXIMUM: ConsumptionPolicy(
        ConsumptionMode.MAXIMUM, 6, 2, 3, None, 240, 6, 0.1, 1),
}


def consumption_policy(mode: Any = ConsumptionMode.BALANCED) -> ConsumptionPolicy:
    return POLICIES[ConsumptionMode.coerce(mode)]
