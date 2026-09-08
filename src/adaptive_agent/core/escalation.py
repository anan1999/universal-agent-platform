from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from adaptive_agent.core.models import Receipt, Task


class FailureKind(StrEnum):
    EXECUTION = "execution_failure"
    TOOL = "tool_failure"
    TASK = "task_failure"
    REASONING = "reasoning_failure"
    TIMEOUT = "timeout"
    ENVIRONMENT = "environment_failure"


@dataclass(slots=True)
class EscalationDecision:
    escalate: bool
    failure_kind: FailureKind
    next_model_class: str | None
    next_reasoning: str | None
    reason: str


class EscalationManager:
    """Decides whether a stronger model could plausibly fix a failure.

    Failure classification is provider-neutral: it matches on the *shape* of the
    error code, so a new provider gets correct escalation behaviour by naming
    its codes `<PROVIDER>_NOT_FOUND`, `<PROVIDER>_AUTH_ERROR`, and so on.
    """

    #: Suffixes that mean "the environment is wrong", which no model can fix.
    ENVIRONMENT_SUFFIXES = ("NOT_FOUND", "AUTH", "AUTH_ERROR", "INVALID_ARGUMENT",
                            "INVALID_RESPONSE", "CONNECTION", "CAPABILITY_UNAVAILABLE",
                            "NOT_IMPLEMENTED", "UNAVAILABLE")
    TIMEOUT_SUFFIX = "TIMEOUT"

    def __init__(self, max_escalations: int = 2):
        self.max_escalations = max_escalations

    def decide(self, task: Task, receipt: Receipt, attempts: int) -> EscalationDecision:
        kind = self.classify(receipt)
        if attempts >= self.max_escalations:
            return EscalationDecision(False, kind, None, None, "Per-task escalation budget exhausted.")
        if kind in {FailureKind.ENVIRONMENT, FailureKind.TOOL, FailureKind.TIMEOUT}:
            return EscalationDecision(False, kind, None, None, f"{kind.value} cannot be solved by a stronger model.")
        if not receipt.needs_escalation and receipt.confidence != "low":
            return EscalationDecision(False, kind, None, None, "Result does not request escalation.")
        next_class = "standard" if task.model_class == "cheap" else "strong" if task.model_class == "standard" else None
        if not next_class:
            return EscalationDecision(False, kind, None, None, "No higher safe route remains.")
        return EscalationDecision(True, kind, next_class, "medium" if next_class == "standard" else "high",
                                  f"Escalating {kind.value} within task budget.")

    def classify(self, receipt: Receipt) -> FailureKind:
        code = (receipt.error_code or "").upper()
        if code.endswith(self.ENVIRONMENT_SUFFIXES):
            return FailureKind.ENVIRONMENT
        if code.endswith(self.TIMEOUT_SUFFIX):
            return FailureKind.TIMEOUT
        if receipt.error_code and "TOOL" in receipt.error_code:
            return FailureKind.TOOL
        if receipt.confidence == "low" or receipt.needs_escalation:
            return FailureKind.REASONING
        if receipt.status in {"failed", "blocked"}:
            return FailureKind.TASK
        return FailureKind.EXECUTION

