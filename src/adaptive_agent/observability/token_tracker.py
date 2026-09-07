from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ContextBudget:
    max_tokens: int = 32000
    files_read: set[str] = field(default_factory=set)
    tokens_in: int = 0
    tokens_out: int = 0
    messages: int = 0
    assignments: int = 0

    @property
    def health(self) -> str:
        ratio = (self.tokens_in + self.tokens_out) / max(self.max_tokens, 1)
        if self.assignments >= 3 or ratio >= 0.85:
            return "fatigued"
        if ratio >= 0.65:
            return "large"
        if ratio >= 0.25:
            return "healthy"
        return "fresh"

    def warnings(self, model_class: str = "standard", task_type: str = "") -> list[str]:
        warnings = []
        if self.health == "fatigued":
            warnings.append("Agent context is fatigued; rotate the instance.")
        if model_class in {"strong", "strongest"} and task_type in {"file_discovery", "build", "log_cleanup"}:
            warnings.append("Strong model used for mechanical work; route to a cheaper model class.")
        return warnings

