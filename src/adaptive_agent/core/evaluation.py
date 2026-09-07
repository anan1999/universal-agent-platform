"""Evaluation strategies.

Testing and review are software-shaped instances of a general idea: *how do we
know this work is good enough?* Profiles declare which
strategies apply; the core only knows the three ways a strategy can be carried
out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Iterable

from adaptive_agent.core.capabilities import normalize


class EvaluationKind(StrEnum):
    #: A deterministic tool decides.
    DETERMINISTIC = "deterministic"
    #: A reasoning agent reviews the output.
    AGENT_REVIEW = "agent_review"
    #: A human must confirm.
    HUMAN = "human"


@dataclass(slots=True)
class EvaluationStrategy:
    id: str
    name: str = ""
    kind: EvaluationKind = EvaluationKind.AGENT_REVIEW
    description: str = ""
    #: Capabilities the evaluating agent or tool needs.
    capabilities: list[str] = field(default_factory=list)
    #: For DETERMINISTIC strategies, the tool that decides.
    tool: str | None = None
    #: Only applies when the profile also contributes a matching role.
    blocking: bool = True

    def __post_init__(self) -> None:
        self.name = self.name or self.id.replace("_", " ").title()
        self.capabilities = [normalize(item) for item in self.capabilities]
        self.kind = EvaluationKind(self.kind) if not isinstance(self.kind, EvaluationKind) else self.kind

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "kind": self.kind.value,
                "description": self.description, "capabilities": list(self.capabilities),
                "tool": self.tool, "blocking": self.blocking}


BUILT_IN_STRATEGIES: tuple[EvaluationStrategy, ...] = (
    # Software
    EvaluationStrategy("unit_tests", kind=EvaluationKind.DETERMINISTIC, tool="project_test",
                       description="Run the project's allowlisted test command.",
                       capabilities=["testing", "test"]),
    EvaluationStrategy("build_check", kind=EvaluationKind.DETERMINISTIC, tool="project_build",
                       description="Confirm the project still builds.", capabilities=["build"]),
    EvaluationStrategy("code_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Independent correctness and regression review.",
                       capabilities=["code_review", "regression_review"]),
    # UI / UX
    EvaluationStrategy("heuristic_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Usability heuristic walkthrough.", capabilities=["usability"]),
    EvaluationStrategy("accessibility_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check the design against accessibility requirements.",
                       capabilities=["accessibility"]),
    # Research
    EvaluationStrategy("citation_validation", kind=EvaluationKind.AGENT_REVIEW,
                       description="Verify every claim maps to a real source.",
                       capabilities=["citation_review"]),
    EvaluationStrategy("evidence_coverage", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check the evidence actually covers the question.",
                       capabilities=["evidence_analysis"]),
    # Design
    EvaluationStrategy("brief_compliance", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check the output against the design brief.",
                       capabilities=["visual_review"]),
    EvaluationStrategy("visual_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Critique composition, typography, and hierarchy.",
                       capabilities=["visual_review"]),
    # AI / data
    EvaluationStrategy("accuracy_check", kind=EvaluationKind.AGENT_REVIEW,
                       description="Compare measured accuracy against the baseline.",
                       capabilities=["evaluation", "accuracy_analysis"]),
    EvaluationStrategy("latency_benchmark", kind=EvaluationKind.DETERMINISTIC, tool="benchmark_run",
                       description="Measure latency against the baseline.",
                       capabilities=["benchmarking", "latency_analysis"]),
    EvaluationStrategy("regression_check", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check for behavioural regressions.",
                       capabilities=["regression_analysis", "evaluation"]),
    EvaluationStrategy("data_quality_check", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check completeness and validity of the data used.",
                       capabilities=["data_quality"]),
    EvaluationStrategy("method_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check the analytical method supports the conclusion.",
                       capabilities=["statistics", "evaluation"]),
    # Product / writing / generic
    EvaluationStrategy("requirement_coverage", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check every stated requirement is addressed.",
                       capabilities=["requirements", "evaluation"]),
    EvaluationStrategy("acceptance_criteria_check", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check the acceptance criteria are testable and met.",
                       capabilities=["acceptance_criteria"]),
    EvaluationStrategy("content_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check accuracy, completeness, and voice.",
                       capabilities=["editing", "content_review"]),
    EvaluationStrategy("pipeline_check", kind=EvaluationKind.DETERMINISTIC, tool="project_build",
                       description="Confirm the pipeline configuration is valid.",
                       capabilities=["ci_cd"]),
    EvaluationStrategy("rollback_review", kind=EvaluationKind.AGENT_REVIEW,
                       description="Check blast radius and rollback safety.",
                       capabilities=["deployment", "evaluation"]),
    EvaluationStrategy("goal_coverage", kind=EvaluationKind.DETERMINISTIC, tool="goal_coverage",
                       description="Check the receipts against the stated goal.",
                       capabilities=["evaluation", "goal_analysis"], blocking=False),
)


class EvaluationRegistry:
    def __init__(self, strategies: Iterable[EvaluationStrategy] = BUILT_IN_STRATEGIES):
        self._strategies = {item.id: item for item in strategies}

    def register(self, strategy: EvaluationStrategy, replace: bool = False) -> None:
        if strategy.id in self._strategies and not replace:
            raise ValueError(f"evaluation strategy already registered: {strategy.id}")
        self._strategies[strategy.id] = strategy

    def get(self, strategy_id: str) -> EvaluationStrategy | None:
        return self._strategies.get(strategy_id)

    def all(self) -> list[EvaluationStrategy]:
        return [self._strategies[key] for key in sorted(self._strategies)]

    def resolve(self, strategy_ids: Iterable[str]) -> list[EvaluationStrategy]:
        """Resolve declared strategy ids. Unknown ids are skipped, never fatal."""
        resolved = []
        for identifier in strategy_ids:
            strategy = self._strategies.get(identifier)
            if strategy is not None and strategy not in resolved:
                resolved.append(strategy)
        return resolved

    def to_dict(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.all()]
