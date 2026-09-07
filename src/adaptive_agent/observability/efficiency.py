from dataclasses import asdict, dataclass

from adaptive_agent.core.models import Receipt, Task


@dataclass(slots=True)
class EfficiencyWarning:
    code: str
    message: str
    recommendation: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class TokenEfficiencyAnalyzer:
    """Flags spend that the task did not need. Names no model and no provider."""

    #: Work that is well-defined enough that a cheaper model, or a deterministic
    #: tool, is normally sufficient. Extendable by profiles and plugins.
    MECHANICAL = {"repository_search", "log_analysis", "build", "formatting", "file_discovery",
                  "workspace_inspection", "summarization", "data_exploration"}

    def analyze(self, task: Task, receipt: Receipt | None = None) -> list[EfficiencyWarning]:
        warnings = []
        if task.model_class in {"strong", "strongest"} and task.metadata.get("task_type", "") in self.MECHANICAL:
            warnings.append(EfficiencyWarning(
                "STRONG_FOR_MECHANICAL", "A strong model was used for mechanical work.",
                "Route comparable low-risk work to a cheaper model class, or to a deterministic tool."))
        if receipt and receipt.retry_count > 2:
            warnings.append(EfficiencyWarning("EXCESSIVE_ESCALATION", "Task exceeded the normal escalation budget.", "Inspect environment and task contract before retrying."))
        if receipt and len(" ".join(receipt.findings).split()) > 500:
            warnings.append(EfficiencyWarning("LARGE_RECEIPT", "Receipt is larger than the downstream context budget.", "Forward a bounded summary and relevant file ranges."))
        return warnings

