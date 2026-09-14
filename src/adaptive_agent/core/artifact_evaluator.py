"""Deterministic-first artifact evaluation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from adaptive_agent.core.models import Receipt, Task


@dataclass(slots=True)
class ArtifactQuality:
    passed: bool
    correctness: float | None = None
    completeness: float | None = None
    format_quality: float | None = None
    domain_constraints: float | None = None
    deterministic_validation: bool = False
    evidence: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactEvaluator(Protocol):
    id: str

    def evaluate(self, task: Task, receipt: Receipt, workspace: Path) -> ArtifactQuality: ...


class DeclaredArtifactEvaluator:
    """Validate explicit artifact contracts without trusting an Agent's prose."""

    id = "declared_artifact"

    def evaluate(self, task: Task, receipt: Receipt, workspace: Path) -> ArtifactQuality:
        required_files = list(task.metadata.get("required_artifacts", []))
        required_sections = list(task.metadata.get("required_sections", []))
        failures, evidence, artifact_text = [], [], []
        for relative in required_files:
            target = (workspace / relative).resolve()
            if workspace.resolve() not in target.parents and target != workspace.resolve():
                failures.append(f"artifact escapes workspace: {relative}")
            elif not target.is_file():
                failures.append(f"missing artifact: {relative}")
            else:
                evidence.append(f"artifact exists: {relative}")
                try:
                    artifact_text.append(target.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    failures.append(f"unreadable artifact: {relative}")
        combined = "\n".join(artifact_text)
        for section in required_sections:
            if not required_files:
                failures.append(f"cannot verify required section without artifact files: {section}")
            elif section.lower() not in combined.lower():
                failures.append(f"missing required section in artifacts: {section}")
            else:
                evidence.append(f"required section present in artifact: {section}")
        passed = not failures
        return ArtifactQuality(passed, 1.0 if passed else 0.0,
                               1.0 if passed else 0.0, deterministic_validation=True,
                               evidence=evidence, failures=failures)
